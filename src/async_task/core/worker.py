import asyncio
import logging
import signal
from collections.abc import Sequence
from datetime import datetime

from ..drivers.base_driver import BaseDriver
from ..serializers.base_serializer import BaseSerializer
from ..serializers.msgpack_serializer import MsgpackSerializer
from .task import Task

logger = logging.getLogger(__name__)


class Worker:
    """Worker process that consumes and executes tasks from queues.

    The worker continuously polls configured queues for tasks and executes them
    asynchronously with respect to the concurrency limit. Supports graceful shutdown
    via SIGTERM/SIGINT signals.

    Architecture:
    - Continuous polling loop with sleep to prevent CPU spinning
    - Round-robin queue checking for fair task distribution
    - Respects concurrency limit using asyncio task management
    - Automatic retry handling with exponential backoff
    - Graceful shutdown that waits for in-flight tasks

    Modes:
    - Production: max_tasks=None (runs indefinitely until signaled)
    - Testing: max_tasks=N (processes exactly N tasks then exits)
    - Batch: max_tasks=N (processes N tasks from queue then exits)

    Attributes:
        queue_driver: An instance of a driver that extends BaseDriver for queue operations
        queues: List of queue names to poll (in priority order)
        concurrency: Maximum number of concurrent task executions
        max_tasks: Optional limit on total tasks to process

    Key behaviors:
    - Polls queues in round-robin order for fairness
    - Sleeps 0.1s when no tasks available (prevents CPU spinning)
    - Respects concurrency limit with asyncio.wait()
    - Handles task failures with retry logic
    - Graceful shutdown on SIGTERM/SIGINT
    """

    def __init__(
        self,
        queue_driver: BaseDriver,
        queues: Sequence[str] | None = None,
        concurrency: int = 10,
        max_tasks: int | None = None,  # None = run indefinitely (production default)
        serializer: BaseSerializer | None = None,
    ) -> None:
        self.queue_driver = queue_driver
        self.queues = list(queues) if queues else ["default"]
        self.concurrency = concurrency
        self.max_tasks = max_tasks  # None = continuous operation, N = stop after N tasks
        self.serializer = serializer or MsgpackSerializer()

        self._running = False
        self._tasks: set[asyncio.Task] = set()
        self._tasks_processed = 0

    async def start(self) -> None:
        """Start the worker loop and block until shutdown.

        Initializes signal handlers for graceful shutdown (SIGTERM, SIGINT)
        and runs the main polling loop. Blocks until:
        - Shutdown signal received (SIGTERM/SIGINT)
        - max_tasks limit reached (if configured)
        - Unhandled exception occurs

        Ensures cleanup is always performed via finally block.

        Example:
            worker = Worker(queue_driver, queues=['default', 'high-priority'])
            await worker.start()  # Blocks until shutdown
        """
        self._running = True

        # Ensure driver is connected
        await self.queue_driver.connect()

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        logger.info(f"Worker starting: queues={self.queues}, concurrency={self.concurrency}")

        try:
            await self._run()
        finally:
            await self._cleanup()

    async def _run(self):
        """Main worker loop - continuously processes tasks until stopped.

        Loop behavior:
        1. Check if max_tasks limit reached (exit if true)
        2. Wait for concurrency slot if at limit
        3. Fetch next task from queues (round-robin)
        4. If task found: spawn async task for processing
        5. If no task found: sleep 0.1s to avoid CPU spinning
        6. Repeat until self._running becomes False

        Exit conditions:
        - self._running set to False (via signal handler)
        - max_tasks limit reached (if configured)

        Production workers use max_tasks=None for continuous operation.
        Test/batch workers use max_tasks=N to process exactly N tasks.

        Note: The 0.1s sleep prevents CPU spinning when queues are empty,
        providing a good balance between responsiveness and resource usage.

        Alternative: Python 3.11+ can use asyncio.TaskGroup for better
        structured concurrency and automatic exception handling.
        """
        while self._running:
            # Check if we've reached max tasks (used for testing/batch processing)
            if self.max_tasks and self._tasks_processed >= self.max_tasks:
                logger.info(f"Reached max tasks limit: {self.max_tasks}")
                break

            # Check if we can accept more tasks
            if len(self._tasks) >= self.concurrency:
                # Wait for a task to complete
                done, pending = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
                self._tasks = pending
                continue

            # Try to get a task from queues (in priority order)
            if (task_data := await self._fetch_task()) is None:
                # No tasks available, sleep briefly then check again
                # This prevents CPU spinning while still being responsive
                # Note: asyncio.sleep(0) would yield to event loop without delay
                await asyncio.sleep(0.1)
                continue  # Loop continues - worker keeps checking for new tasks

            # Create asyncio task to process task
            task = asyncio.create_task(self._process_task(task_data))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _fetch_task(self) -> bytes | None:
        """Fetch next task from queues in round-robin order.

        Polls each queue in order until a task is found. This provides
        fair distribution across queues (first-listed queues have priority).

        Returns:
            bytes: Serialized task data, or None if all queues empty
        """
        for queue_name in self.queues:
            task_data = await self.queue_driver.dequeue(queue_name)
            if task_data:
                return task_data
        return None

    async def _process_task(self, task_data: bytes) -> None:
        """Process a single task with error handling and timeout support.

        Workflow:
        1. Deserialize task from bytes
        2. Execute task.handle() with optional timeout
        3. Handle failures with retry logic
        4. Increment processed task counter

        Error handling:
        - TimeoutError: Task exceeded configured timeout
        - Exception: General task failure (logged with stacktrace)
        - Both trigger retry logic via _handle_task_failure()

        Args:
            task_data: Serialized task bytes from queue
        """
        task: Task | None = None

        try:
            # Deserialize task
            task = await self._deserialize_task(task_data)

            assert task is not None

            logger.info(f"Processing task {task._task_id}: {task.__class__.__name__}")

            # Execute task with timeout
            if task.timeout:
                await asyncio.wait_for(task.handle(), timeout=task.timeout)
            else:
                await task.handle()

            # Task succeeded - increment counter
            logger.info(f"Task {task._task_id} completed successfully")
            self._tasks_processed += 1

        except TimeoutError:
            assert task is not None
            logger.error(f"Task {task._task_id} timed out")
            await self._handle_task_failure(task, TimeoutError("Task exceeded timeout"))

        except Exception as e:
            assert task is not None
            logger.exception(f"Task {task._task_id} failed: {e}")
            await self._handle_task_failure(task, e)

        # Note: Python 3.11+ ExceptionGroup can be used to collect
        # multiple errors if task spawns subtasks

    async def _handle_task_failure(self, task: Task, exception: Exception) -> None:
        """Handle task failure with intelligent retry logic.

        Retry decision:
        1. Increment task._attempts counter
        2. Check if attempts < max_retries
        3. Call task.should_retry(exception) for custom logic
        4. If both pass: re-enqueue with retry_delay
        5. If retry exhausted: call task.failed() and store error

        Args:
            task: Failed task instance
            exception: Exception that caused the failure
        """
        task._attempts += 1

        # Check if we should retry
        if task._attempts < task.max_retries and task.should_retry(exception):
            logger.info(
                f"Retrying task {task._task_id} (attempt {task._attempts}/{task.max_retries})"
            )

            # Re-enqueue with delay
            serialized_task = await self._serialize_task(task)
            await self.queue_driver.enqueue(task.queue, serialized_task, task.retry_delay)
        else:
            # Task has failed permanently
            logger.error(f"Task {task._task_id} failed permanently after {task._attempts} attempts")

            try:
                await task.failed(exception)
            except Exception as e:
                logger.exception(f"Error in task.failed() handler: {e}")

    async def _deserialize_task(self, task_data: bytes) -> Task:
        """Deserialize task from bytes and reconstruct instance.

        Reconstruction process:
        1. Deserialize bytes to dictionary using queue serializer
        2. Import task class from 'class' field (module.ClassName)
        3. Create task instance without calling __init__
        4. Restore task parameters from 'params' dict
        5. Restore internal metadata (_task_id, _attempts, etc.)

        Args:
            task_data: Serialized task bytes

        Returns:
            Task: Fully reconstructed task instance

        Raises:
            ImportError: If task class cannot be imported
            AttributeError: If task class not found in module
        """
        data = self.serializer.deserialize(task_data)

        # Import task class
        module_name, class_name = data["class"].rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        task_class = getattr(module, class_name)

        # Reconstruct task
        task = task_class.__new__(task_class)
        task.__dict__.update(data["params"])

        # Restore metadata with proper type conversions
        metadata = data["metadata"]
        task._task_id = metadata.get("task_id")
        task._attempts = metadata.get("attempts", 0)

        # Restore dispatched_at as datetime if present
        dispatched_at_str = metadata.get("dispatched_at")
        if dispatched_at_str:
            try:
                task._dispatched_at = datetime.fromisoformat(dispatched_at_str)
            except (ValueError, TypeError):
                # Fallback for older formats or None
                task._dispatched_at = None
        else:
            task._dispatched_at = None

        # Restore task configuration from metadata
        if "max_retries" in metadata:
            task.max_retries = metadata["max_retries"]
        if "retry_delay" in metadata:
            task.retry_delay = metadata["retry_delay"]
        if "timeout" in metadata:
            task.timeout = metadata["timeout"]
        if "queue" in metadata:
            task.queue = metadata["queue"]

        return task

    async def _serialize_task(self, task: Task) -> bytes:
        """Serialize task for re-enqueueing (used for retries).

        Serialization includes:
        - Task class path (for reconstruction)
        - Task parameters (non-internal attributes)
        - Task metadata (_task_id, _attempts, etc.)
        - Task configuration (queue, max_retries, etc.)

        Args:
            task: Task instance to serialize

        Returns:
            bytes: Serialized task data
        """
        task_data = {
            "class": f"{task.__class__.__module__}.{task.__class__.__name__}",
            "params": {k: v for k, v in task.__dict__.items() if not k.startswith("_")},
            "metadata": {
                "task_id": task._task_id,
                "attempts": task._attempts,
                "dispatched_at": task._dispatched_at.isoformat() if task._dispatched_at else None,
                "max_retries": task.max_retries,
                "retry_delay": task.retry_delay,
                "timeout": task.timeout,
                "queue": task.queue,
            },
        }

        return self.serializer.serialize(task_data)

    def _handle_shutdown(self) -> None:
        """Handle graceful shutdown."""
        logger.info("Shutdown signal received")
        self._running = False

    async def _cleanup(self) -> None:
        """Cleanup on shutdown - wait for in-flight tasks to complete.

        Ensures graceful shutdown by waiting for all currently executing
        tasks to finish before exiting. This prevents task loss and ensures
        clean resource cleanup.
        """
        logger.info("Waiting for running tasks to complete...")

        if self._tasks:
            await asyncio.wait(self._tasks)

        # Disconnect driver
        await self.queue_driver.disconnect()

        logger.info("Worker shutdown complete")
