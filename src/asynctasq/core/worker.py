import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
import logging
import signal
import socket
import traceback
import uuid

from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.serializers import BaseSerializer, MsgpackSerializer
from asynctasq.tasks import BaseTask, ProcessTask, TaskService

from .events import EventEmitter, EventType, TaskEvent, WorkerEvent

logger = logging.getLogger(__name__)


class Worker:
    """Worker process that consumes and executes tasks from queues.

    The worker continuously polls configured queues for tasks and executes them
    asynchronously with respect to the concurrency limit. Supports graceful shutdown
    via SIGTERM/SIGINT signals.

    ## Architecture

    - **Continuous polling loop**: Prevents CPU spinning with 0.1s sleep when idle
    - **Round-robin queue checking**: Ensures fair task distribution across queues
    - **Concurrency control**: Uses asyncio.wait() to respect concurrency limits
    - **Automatic retry handling**: Supports exponential backoff and configurable retry logic
    - **Graceful shutdown**: Waits for in-flight tasks before exiting on SIGTERM/SIGINT

    ## Best Practices Implemented

    - **Timeout handling**: Task execution respects configured timeouts (via TaskService)
    - **Structured logging**: All errors logged with context (task_id, worker_id, queue)
    - **Event emission**: Integration points for observability and monitoring
    - **Error resilience**: Distinguishes deserialization failures from execution failures
    - **Resource cleanup**: Ensures proper driver disconnection and task service cleanup

    ## Modes

    - **Production**: max_tasks=None (runs indefinitely until signaled)
    - **Testing**: max_tasks=N (processes exactly N tasks then exits)
    - **Batch**: max_tasks=N (processes N tasks from queue then exits)

    ## Attributes

        queue_driver: An instance of a driver that extends BaseDriver
        queues: List of queue names to poll (in priority order)
        concurrency: Maximum number of concurrent task executions
        max_tasks: Optional limit on total tasks to process (None = unlimited)
        event_emitter: Optional EventEmitter for observability
        heartbeat_interval: Seconds between heartbeat events (default: 60)

    ## Signal Handling

    - SIGTERM: Graceful shutdown with task draining
    - SIGINT: Same as SIGTERM (Ctrl+C)
    """

    def __init__(
        self,
        queue_driver: BaseDriver,
        queues: Sequence[str] | None = None,
        concurrency: int = 10,
        max_tasks: int | None = None,  # None = run indefinitely (production default)
        serializer: BaseSerializer | None = None,
        event_emitter: EventEmitter | None = None,
        worker_id: str | None = None,
        heartbeat_interval: float = 60.0,
        process_pool_size: int | None = None,
        process_pool_max_tasks_per_child: int | None = None,
    ) -> None:
        self.queue_driver = queue_driver
        self.queues = list(queues) if queues else ["default"]
        self.concurrency = concurrency
        self.max_tasks = max_tasks  # None = continuous operation, N = stop after N tasks
        self.serializer = serializer or MsgpackSerializer()
        self.event_emitter = event_emitter
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.hostname = socket.gethostname()
        self.heartbeat_interval = heartbeat_interval
        self.process_pool_size = process_pool_size
        self.process_pool_max_tasks_per_child = process_pool_max_tasks_per_child

        self._running = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._tasks_processed = 0
        self._start_time: datetime | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._task_service = TaskService(serializer=self.serializer)

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
        self._start_time = datetime.now(UTC)

        # Ensure driver is connected
        await self.queue_driver.connect()

        # Initialize ProcessTask pool if configured
        if self.process_pool_size is not None or self.process_pool_max_tasks_per_child is not None:
            logger.info(
                "Initializing ProcessTask pool: size=%s, max_tasks_per_child=%s",
                self.process_pool_size,
                self.process_pool_max_tasks_per_child,
            )
            ProcessTask.initialize_pool(
                max_workers=self.process_pool_size,
                max_tasks_per_child=self.process_pool_max_tasks_per_child,
            )

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        logger.info(
            "Worker %s starting: queues=%s, concurrency=%d",
            self.worker_id,
            self.queues,
            self.concurrency,
        )

        # Emit worker_online event
        if self.event_emitter:
            await self.event_emitter.emit_worker_event(
                WorkerEvent(
                    event_type=EventType.WORKER_ONLINE,
                    worker_id=self.worker_id,
                    hostname=self.hostname,
                    queues=tuple(self.queues),
                    freq=self.heartbeat_interval,
                )
            )

        # Start heartbeat loop
        if self.event_emitter:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name=f"{self.worker_id}-heartbeat"
            )

        try:
            await self._run()
        finally:
            await self._cleanup()

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat events (default: every 60 seconds).

        The heartbeat contains worker status including:
        - Number of active tasks (currently executing)
        - Total tasks processed
        - Worker uptime
        - Configured queues

        If a worker hasn't sent a heartbeat in 2× the heartbeat interval,
        it should be considered offline by the monitoring system.
        """
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if not self._running:
                    break

                uptime = (
                    int((datetime.now(UTC) - self._start_time).total_seconds())
                    if self._start_time
                    else 0
                )

                if self.event_emitter:
                    await self.event_emitter.emit_worker_event(
                        WorkerEvent(
                            event_type=EventType.WORKER_HEARTBEAT,
                            worker_id=self.worker_id,
                            hostname=self.hostname,
                            freq=self.heartbeat_interval,
                            active=len(self._tasks),
                            processed=self._tasks_processed,
                            queues=tuple(self.queues),
                            uptime_seconds=uptime,
                        )
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Failed to send heartbeat: %s", e)

    async def _run(self) -> None:
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
            fetch_result = await self._fetch_task()
            if fetch_result is None:
                # No tasks available, sleep briefly then check again
                # This prevents CPU spinning while still being responsive
                # Note: asyncio.sleep(0) would yield to event loop without delay
                await asyncio.sleep(0.1)
                continue  # Loop continues - worker keeps checking for new tasks

            task_data, queue_name = fetch_result

            # Create asyncio task to process task
            task = asyncio.create_task(self._process_task(task_data, queue_name))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _fetch_task(self) -> tuple[bytes, str] | None:
        """Fetch next task from queues in round-robin order.

        Polls each queue in order until a task is found. This provides
        fair distribution across queues (first-listed queues have priority).

        Returns:
            tuple[bytes, str]: (Serialized task data, queue name) or None if all queues empty
        """
        for queue_name in self.queues:
            task_data = await self.queue_driver.dequeue(queue_name)
            if task_data:
                return (task_data, queue_name)
        return None

    async def _process_task(self, task_data: bytes, queue_name: str) -> None:
        """Process a single task with error handling and timeout support.

        Workflow:
        1. Deserialize task from bytes
        2. Emit task_started event
        3. Execute task.handle() with optional timeout
        4. Emit task_completed or task_failed event
        5. Handle failures with retry logic
        6. Increment processed task counter

        Error handling:
        - DeserializationError: Re-enqueue raw task_data for retry
        - TimeoutError: Task exceeded configured timeout
        - Exception: General task failure (logged with stacktrace)
        - Both trigger retry logic via _handle_task_failure()

        Args:
            task_data: Serialized task bytes from queue
            queue_name: Name of the queue the task came from
        """
        task: BaseTask | None = None
        start_time = datetime.now(UTC)

        try:
            # Deserialize task
            task = await self._deserialize_task(task_data)

            assert task is not None
            assert task._task_id is not None  # Task ID is set during deserialization

            logger.info(f"Processing task {task._task_id}: {task.__class__.__name__}")

            # Emit task_started event
            if self.event_emitter:
                await self.event_emitter.emit_task_event(
                    TaskEvent(
                        event_type=EventType.TASK_STARTED,
                        task_id=task._task_id,
                        task_name=task.__class__.__name__,
                        queue=queue_name,
                        worker_id=self.worker_id,
                        attempt=task._attempts + 1,
                    )
                )

            # Execute task with timeout (delegated to TaskService)
            await self._task_service.execute_task(task)

            # Calculate duration
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            # Emit task_completed event
            if self.event_emitter:
                await self.event_emitter.emit_task_event(
                    TaskEvent(
                        event_type=EventType.TASK_COMPLETED,
                        task_id=task._task_id,
                        task_name=task.__class__.__name__,
                        queue=queue_name,
                        worker_id=self.worker_id,
                        duration_ms=duration_ms,
                    )
                )

            # Task succeeded - acknowledge and remove from queue
            logger.info(f"Task {task._task_id} completed successfully")
            try:
                # Add timeout to ack to prevent hanging
                await asyncio.wait_for(self.queue_driver.ack(queue_name, task_data), timeout=5.0)
            except TimeoutError:
                logger.error(
                    f"Ack timeout for task {task._task_id} from queue '{queue_name}'. "
                    f"Task completed but may remain in processing list."
                )
            except Exception as ack_error:
                # Log ack error but don't fail the task - it already completed successfully
                logger.error(
                    f"Failed to acknowledge task {task._task_id} from queue '{queue_name}': "
                    f"{ack_error}"
                )
                logger.exception(ack_error)
            self._tasks_processed += 1

        except (ImportError, AttributeError, ValueError, TypeError) as e:
            if task is None:
                # Deserialization failure - re-enqueue raw task_data for retry
                # This allows the task to be retried later (e.g., after code is fixed)
                logger.error(
                    f"Failed to deserialize task from queue '{queue_name}': {e}. "
                    f"Re-enqueuing for retry."
                )
                logger.exception(e)
                # Re-enqueue with a delay to avoid immediate retry loop
                await self.queue_driver.enqueue(queue_name, task_data, delay_seconds=60)
            else:
                # ValueError/TypeError during task execution - handle as task failure
                logger.exception(f"Task {task._task_id} failed: {e}")
                await self._handle_task_failure(task, e, queue_name, start_time)

        except TimeoutError as e:
            if task is None:
                # TimeoutError during deserialization - treat as deserialization failure
                logger.error(
                    f"Deserialization timeout for task from queue '{queue_name}': {e}. "
                    f"Re-enqueuing for retry."
                )
                logger.exception(e)
                await self.queue_driver.enqueue(queue_name, task_data, delay_seconds=60)
            else:
                # TimeoutError during task execution - handle as task failure
                logger.error(f"Task {task._task_id} timed out")
                await self._handle_task_failure(
                    task, TimeoutError("Task exceeded timeout"), queue_name, start_time
                )

        except Exception as e:
            if task is None:
                # Unexpected error during deserialization that we didn't catch above
                logger.error(
                    f"Unexpected error deserializing task from queue '{queue_name}': {e}. "
                    f"Re-enqueuing for retry."
                )
                logger.exception(e)
                await self.queue_driver.enqueue(queue_name, task_data, delay_seconds=60)
            else:
                logger.exception(f"Task {task._task_id} failed: {e}")
                await self._handle_task_failure(task, e, queue_name, start_time)

        # Note: Python 3.11+ ExceptionGroup can be used to collect
        # multiple errors if task spawns subtasks

    async def _handle_task_failure(
        self, task: BaseTask, exception: Exception, queue_name: str, start_time: datetime
    ) -> None:
        """Handle task failure with intelligent retry logic.

        Retry decision:
        1. Check if attempts < max_retries (via TaskService.should_retry)
        2. Call task.should_retry(exception) for custom logic
        3. If both pass: emit task_retrying, increment attempts, and re-enqueue
        4. If retry exhausted: emit task_failed, call task.failed() and store error

        Args:
            task: Failed task instance
            exception: Exception that caused the failure
            queue_name: Name of the queue the task came from
            start_time: When task processing started
        """
        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        task_id = task._task_id or "unknown"  # Fallback for type safety

        # Check if we should retry (uses TaskService for the decision logic)
        if self._task_service.should_retry(task, exception):
            # prepare_for_retry increments attempts and serializes
            serialized_task = self._task_service.prepare_for_retry(task)
            logger.info(f"Retrying task {task_id} (attempt {task._attempts}/{task.max_retries})")

            # Emit task_retrying event
            if self.event_emitter:
                await self.event_emitter.emit_task_event(
                    TaskEvent(
                        event_type=EventType.TASK_RETRYING,
                        task_id=task_id,
                        task_name=task.__class__.__name__,
                        queue=queue_name,
                        worker_id=self.worker_id,
                        attempt=task._attempts,
                        error=str(exception),
                        duration_ms=duration_ms,
                    )
                )

            # Re-enqueue with delay
            await self.queue_driver.enqueue(
                task.queue, serialized_task, delay_seconds=task.retry_delay
            )
        else:
            # Task has failed permanently - increment to reflect the failed attempt
            task._attempts += 1
            logger.error(f"Task {task_id} failed permanently after {task._attempts} attempts")

            # Emit task_failed event
            if self.event_emitter:
                await self.event_emitter.emit_task_event(
                    TaskEvent(
                        event_type=EventType.TASK_FAILED,
                        task_id=task_id,
                        task_name=task.__class__.__name__,
                        queue=queue_name,
                        worker_id=self.worker_id,
                        duration_ms=duration_ms,
                        error=str(exception),
                        traceback=traceback.format_exc(),
                        attempt=task._attempts,
                    )
                )

            # Call task's failed() hook via TaskService
            await self._task_service.handle_task_failed(task, exception)

    async def _deserialize_task(self, task_data: bytes) -> BaseTask:
        """Deserialize task from bytes and reconstruct instance.

        Delegates to TaskService for the actual deserialization logic.

        Args:
            task_data: Serialized task bytes

        Returns:
            Task: Fully reconstructed task instance

        Raises:
            ImportError: If task class cannot be imported
            AttributeError: If task class not found in module
        """
        return await self._task_service.deserialize_task(task_data)

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

        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._tasks:
            await asyncio.wait(self._tasks)

        # Shutdown ProcessTask pool (graceful - wait for in-flight tasks)
        logger.info("Shutting down ProcessTask pool...")
        ProcessTask.shutdown_pool(wait=True)

        # Emit worker_offline event
        if self.event_emitter:
            uptime = (
                int((datetime.now(UTC) - self._start_time).total_seconds())
                if self._start_time
                else 0
            )
            await self.event_emitter.emit_worker_event(
                WorkerEvent(
                    event_type=EventType.WORKER_OFFLINE,
                    worker_id=self.worker_id,
                    hostname=self.hostname,
                    processed=self._tasks_processed,
                    uptime_seconds=uptime,
                )
            )
            await self.event_emitter.close()

        # Disconnect driver
        await self.queue_driver.disconnect()

        logger.info("Worker shutdown complete")
