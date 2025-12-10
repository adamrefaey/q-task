from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Self

from asynctasq.drivers.base_driver import BaseDriver


class BaseTask[T](ABC):
    """Base class for all Async Task AsyncTasQs."""

    # Task configuration (can be overridden by subclasses)
    queue: str = "default"
    max_retries: int = 3
    retry_delay: int = 60  # seconds
    timeout: int | None = None

    # Driver override (optional - set to use specific driver for this task)
    # Can be: "redis", "sqs", "postgres", "mysql", or a BaseDriver instance
    _driver_override: str | BaseDriver | None = None
    _delay_seconds: int | None = None

    def __init__(self, **kwargs: Any) -> None:
        """Initialize task with parameters.

        All kwargs are automatically available as self.param_name
        """
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Metadata (managed internally)
        self._task_id: str | None = None
        self._attempts: int = 0
        self._dispatched_at: datetime | None = None

    @abstractmethod
    async def handle(self) -> T:
        """Execute the task. Must be implemented by subclasses.

        This is where your business logic goes.
        """
        pass

    async def failed(self, exception: Exception) -> None:  # noqa: B027
        """Called when task fails after all retries.

        Override this to handle failures (logging, alerting, etc.)
        """
        pass

    def should_retry(self, exception: Exception) -> bool:
        """Determine if task should retry after an exception.

        Override for custom retry logic.
        """
        return True

    # Syntactic sugar methods (optional - can pass these to dispatch() instead)
    def on_queue(self, queue_name: str) -> Self:
        """Set the queue for this task."""
        self.queue = queue_name
        return self

    def delay(self, seconds: int) -> Self:
        """Configure delay for task execution.

        This method ONLY configures the delay - it does NOT dispatch the task.
        You must call dispatch() after this to actually queue the task.

        Args:
            seconds: Number of seconds to delay task execution (must be > 0)

        Returns:
            self: BaseTask instance for method chaining

        Example:
            # Class-based - delay then dispatch
            await MyTask(param=value).delay(60).dispatch()

            # Function-based - delay then dispatch
            await my_func(param=value).delay(60).dispatch()

            # Alternative: pass delay to dispatch() directly
            await my_func.dispatch(param=value, delay=60)
        """
        self._delay_seconds = seconds
        return self

    def retry_after(self, seconds: int) -> Self:
        """Configure retry delay for this task.

        Args:
            seconds: Seconds to wait between retry attempts

        Returns:
            self: BaseTask instance for method chaining
        """
        self.retry_delay = seconds
        return self

    async def dispatch(self) -> str:
        """Dispatch this task instance to the configured queue.

        This method sends the task to the queue for asynchronous execution.
        The dispatcher will serialize the task and enqueue it using the
        appropriate driver (Redis/SQS/Postgres/MySQL).

        Returns:
            task_id: UUID string uniquely identifying the dispatched task

        Raises:
            RuntimeError: If dispatcher not initialized and no config found
            ConnectionError: If driver connection fails

        Example:
            # Class-based - immediate dispatch
            task_id = await MyTask(param=value).dispatch()

            # Class-based - with delay
            task_id = await MyTask(param=value).delay(60).dispatch()

            # Function-based - immediate dispatch
            task_id = await my_func(param=value).dispatch()

            # Function-based - with delay
            task_id = await my_func(param=value).delay(60).dispatch()
        """
        from asynctasq.core.dispatcher import get_dispatcher

        # Pass driver override to get_dispatcher if set
        driver_override = getattr(self, "_driver_override", None)
        return await get_dispatcher(driver_override).dispatch(self)
