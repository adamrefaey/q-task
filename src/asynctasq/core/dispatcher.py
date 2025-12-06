from datetime import UTC, datetime
import inspect
import logging
from typing import TYPE_CHECKING, cast
import uuid

from asynctasq.config import Config, get_global_config
from asynctasq.drivers import DriverType
from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.serializers import BaseSerializer, MsgpackSerializer

from .driver_factory import DriverFactory
from .events import EventEmitter, EventType, TaskEvent

if TYPE_CHECKING:
    from .task import FunctionTask, Task
else:
    from .task import FunctionTask

logger = logging.getLogger(__name__)


class Dispatcher:
    """Dispatches tasks to queues using queue drivers.

    The Dispatcher manages task serialization and enqueueing across different
    queue drivers (Redis, SQS, Postgres, MySQL). It supports per-task driver overrides.

    Attributes:
        driver: Default queue driver for tasks without driver override
        serializer: Task serializer (default: MsgpackSerializer)
        event_emitter: Optional event emitter for monitoring integration
    """

    def __init__(
        self,
        driver: BaseDriver,
        serializer: BaseSerializer | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self.driver = driver
        self.serializer = serializer or MsgpackSerializer()
        self.event_emitter = event_emitter
        self._driver_cache: dict[str, BaseDriver] = {}  # Cache for driver overrides

    def _get_driver(self, task: "Task") -> BaseDriver:
        """Get the appropriate driver for this task.

        Resolution order:
        1. Task's _driver_override attribute (BaseDriver instance or string)
        2. Global default driver
        """
        driver_override: BaseDriver | DriverType | None = getattr(task, "_driver_override", None)

        if driver_override is None:
            return self.driver

        # If driver_override is already a BaseDriver instance
        if isinstance(driver_override, BaseDriver):
            logger.debug(f"Using task-specific driver instance for {task.__class__.__name__}")
            return driver_override

        # If driver_override is a string, create driver from config
        if isinstance(driver_override, str):
            cache_key = driver_override
            if cache_key not in self._driver_cache:
                logger.debug(
                    f"Creating driver override '{driver_override}' for {task.__class__.__name__}"
                )
                config = get_global_config()
                self._driver_cache[cache_key] = DriverFactory.create_from_config(
                    config, driver_type=cast(DriverType, driver_override)
                )
            return self._driver_cache[cache_key]

        return self.driver

    async def dispatch(
        self,
        task: "Task",
        queue: str | None = None,
        delay: int | None = None,
    ) -> str:
        """Dispatch a task to the queue.

        Args:
            task: Task instance to dispatch
            queue: Queue name (overrides task.queue if set)
            delay: Delay in seconds (overrides task._delay_seconds if set)

        Returns:
            Task ID (UUID string)
        """
        # Generate task ID
        task_id = str(uuid.uuid4())
        task._task_id = task_id
        task._dispatched_at = datetime.now(UTC)

        # Determine queue and delay
        target_queue = queue or task.queue
        if delay is not None:
            delay_seconds = delay
        else:
            delay_seconds = getattr(task, "_delay_seconds", None) or 0

        # Get driver and serialize task
        driver = self._get_driver(task)
        driver_type = driver.__class__.__name__
        serialized_task = self._serialize_task(task)

        # Enqueue
        await driver.enqueue(target_queue, serialized_task, delay_seconds)

        # Emit task_enqueued event
        if self.event_emitter:
            await self.event_emitter.emit_task_event(
                TaskEvent(
                    event_type=EventType.TASK_ENQUEUED,
                    task_id=task_id,
                    task_name=task.__class__.__name__,
                    queue=target_queue,
                    worker_id="dispatcher",  # Not yet assigned to a worker
                )
            )

        logger.info(
            f"Dispatching task {task_id}: {task.__class__.__name__} "
            f"to queue '{target_queue}' using {driver_type}"
            + (f" with {delay_seconds}s delay" if delay_seconds > 0 else "")
        )

        return task_id

    def _serialize_task(self, task: "Task") -> bytes:
        """Serialize task for queue storage."""
        # Filter out private attributes and callable objects (like functions)
        params = {
            k: v for k, v in task.__dict__.items() if not k.startswith("_") and not callable(v)
        }

        # Build metadata
        metadata = {
            "task_id": task._task_id,
            "attempts": task._attempts,
            "dispatched_at": task._dispatched_at.isoformat()
            if task._dispatched_at is not None
            else "",
            "max_retries": task.max_retries,
            "retry_delay": task.retry_delay,
            "timeout": task.timeout,
            "queue": task.queue,
        }

        # For FunctionTask, store function reference instead of function object
        if isinstance(task, FunctionTask):
            func = task.func
            metadata["func_name"] = func.__name__

            # Handle __main__ module specially - store file path instead
            if func.__module__ == "__main__":
                try:
                    file_path = inspect.getfile(func)
                    metadata["func_module"] = "__main__"
                    metadata["func_file"] = file_path
                except (TypeError, OSError):
                    # Fallback if we can't get the file path
                    metadata["func_module"] = func.__module__
            else:
                metadata["func_module"] = func.__module__

        task_data = {
            "class": f"{task.__class__.__module__}.{task.__class__.__name__}",
            "params": params,
            "metadata": metadata,
        }
        return self.serializer.serialize(task_data)


# Global dispatcher management
_dispatchers: dict[str, tuple[Dispatcher, BaseDriver]] = {}


def get_dispatcher(driver: str | BaseDriver | None = None) -> Dispatcher:
    """Get dispatcher singleton for the specified driver.

    Lazy initialization: creates dispatcher on first access.

    Args:
        driver: Optional driver specification (None = use default from config)

    Returns:
        Dispatcher instance
    """
    global _dispatchers

    # Determine cache key
    if driver is None:
        driver_key = "default"
    elif isinstance(driver, str):
        driver_key = driver
    else:
        driver_key = f"instance_{id(driver)}"

    # Return cached if exists
    if driver_key in _dispatchers:
        return _dispatchers[driver_key][0]

    config = get_global_config()
    if config is None:
        config = Config.from_env()

    # Create driver
    if isinstance(driver, str):
        driver_instance = DriverFactory.create_from_config(
            config, driver_type=cast(DriverType, driver)
        )
    elif driver is None:
        driver_instance = DriverFactory.create_from_config(config)
    else:
        driver_instance = driver

    # Create event emitter for monitoring integration
    from .events import create_event_emitter

    event_emitter = create_event_emitter()

    # Create dispatcher with event emitter
    dispatcher = Dispatcher(driver_instance, event_emitter=event_emitter)
    _dispatchers[driver_key] = (dispatcher, driver_instance)

    logger.debug(f"Created dispatcher for driver: {driver_key}")

    return dispatcher


async def cleanup():
    """Cleanup all dispatchers and drivers."""
    global _dispatchers

    if not _dispatchers:
        logger.debug("No dispatchers to cleanup")
        return

    logger.info(f"Cleaning up {len(_dispatchers)} dispatcher(s)")

    for driver_key, (dispatcher, driver) in _dispatchers.items():
        try:
            # Close event emitter if present
            event_emitter = getattr(dispatcher, "event_emitter", None)
            if event_emitter:
                await event_emitter.close()
            await driver.disconnect()
            logger.debug(f"Successfully cleaned up dispatcher: {driver_key}")
        except Exception as e:
            logger.exception(f"Error disconnecting driver {driver_key}: {e}")

    _dispatchers.clear()
    logger.info("Dispatcher cleanup complete")
