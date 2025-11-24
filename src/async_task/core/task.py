import asyncio
import functools
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any, Generic, Protocol, Self, TypeVar, overload

from ..drivers.base_driver import BaseDriver

T = TypeVar("T")


class Task(ABC, Generic[T]):
    """Base class for all Async Task tasks."""

    # Task configuration (can be overridden by subclasses)
    queue: str = "default"
    max_retries: int = 3
    retry_delay: int = 60  # seconds
    timeout: int | None = None

    # Driver override (optional - set to use specific driver for this task)
    # Can be: "redis", "sqs", "memory", or a BaseDriver instance
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

    async def failed(self, exception: Exception) -> None:
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
            self: Task instance for method chaining

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
            self: Task instance for method chaining
        """
        self.retry_delay = seconds
        return self

    async def dispatch(self) -> str:
        """Dispatch this task instance to the configured queue.

        This method sends the task to the queue for asynchronous execution.
        The dispatcher will serialize the task and enqueue it using the
        appropriate driver (Redis/SQS/Memory).

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
        from .dispatcher import get_dispatcher

        # Pass driver override to get_dispatcher if set
        driver_override = getattr(self, "_driver_override", None)
        return await get_dispatcher(driver_override).dispatch(self)


# Sync task support
class SyncTask(Task[T]):
    """Synchronous task that will be run in thread pool."""

    @abstractmethod
    def handle_sync(self) -> T:
        """Synchronous handle method."""
        pass

    async def handle(self) -> T:
        """Wrap sync method in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.handle_sync)


# Function-based task support
class FunctionTask(Task[T]):
    """Wrapper for function-based tasks."""

    def __init__(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs

        # Extract task configuration from function attributes (set by @task decorator)
        self.queue = getattr(func, "_task_queue", "default")
        self.max_retries = getattr(func, "_task_max_retries", 3)
        self.retry_delay = getattr(func, "_task_retry_delay", 60)
        self.timeout = getattr(func, "_task_timeout", None)
        self._driver_override = getattr(func, "_task_driver", None)

        # Initialize parent
        super().__init__()

    async def handle(self) -> T:
        """Execute the wrapped function."""
        if inspect.iscoroutinefunction(self.func):
            return await self.func(*self.args, **self.kwargs)
        else:
            # Run sync function in thread pool
            loop = asyncio.get_event_loop()
            # Use functools.partial to handle kwargs with run_in_executor
            partial_func = functools.partial(self.func, *self.args, **self.kwargs)
            return await loop.run_in_executor(None, partial_func)


# Type for decorated function with dispatch method
class TaskFunction(Protocol[T]):
    """Protocol for a function decorated with @task."""

    __name__: str
    __doc__: str | None
    _task_queue: str
    _task_max_retries: int
    _task_retry_delay: int
    _task_timeout: int | None
    _task_driver: str | BaseDriver | None
    _is_task: bool

    async def dispatch(self, *args: Any, **kwargs: Any) -> str:
        """Dispatch this function as a task."""
        ...

    def __call__(self, *args: Any, **kwargs: Any) -> FunctionTask[T]:
        """Create task instance for configuration chaining."""
        ...


# Decorator for function-based tasks
@overload
def task(_func: Callable[..., T], /) -> TaskFunction[T]:
    """Overload for @task (without parentheses)."""
    ...


@overload
def task(
    _func: None = None,
    /,
    *,
    queue: str = "default",
    max_retries: int = 3,
    retry_delay: int = 60,
    timeout: int | None = None,
    driver: str | BaseDriver | None = None,
) -> Callable[[Callable[..., T]], TaskFunction[T]]:
    """Overload for @task(...) (with keyword arguments)."""
    ...


def task(
    _func: Callable[..., T] | None = None,
    /,  # Positional-only: prevents _func from being passed as keyword argument
    *,
    queue: str = "default",
    max_retries: int = 3,
    retry_delay: int = 60,
    timeout: int | None = None,
    driver: str | BaseDriver | None = None,
) -> TaskFunction[T] | Callable[[Callable[..., T]], TaskFunction[T]]:
    """Decorator to mark a function as a task.

    This decorator can be used in two ways:
    1. Without parentheses: @task
    2. With keyword arguments: @task(queue='emails', max_retries=5)

    The `_func` parameter is used internally to detect when the decorator
    is called without parentheses. All other parameters must be passed as
    keyword arguments.

    Args:
        _func: Internal parameter - the function being decorated (when used without parentheses)
        queue: Queue name for this task
        max_retries: Maximum retry attempts
        retry_delay: Delay between retries (seconds)
        timeout: Task timeout (seconds)
        driver: Driver override - can be:
            - String: "redis", "sqs", "memory" (uses global config for that driver)
            - BaseDriver instance: Custom driver instance
            - None: Uses global config (default)

    Returns:
        - TaskFunction[T]: When used as @task (without parentheses)
        - Callable that returns TaskFunction[T]: When used as @task(...) (with parameters)

    Usage:
        # Without arguments (uses defaults)
        @task
        async def simple_task():
            pass

        # With keyword arguments
        @task(queue='emails', max_retries=5)
        async def send_email(user_id: int, message: str):
            # Your logic here
            pass

        # With driver override
        @task(queue='critical', driver='redis')
        async def critical_task(data: dict):
            # This task always uses Redis, regardless of global config
            pass

        # Dispatch it
        await send_email.dispatch(user_id=123, message="Hello")
    """

    def decorator(func: Callable[..., T]) -> TaskFunction[T]:
        # Store task configuration on function
        func._task_queue = queue  # type: ignore[attr-defined]
        func._task_max_retries = max_retries  # type: ignore[attr-defined]
        func._task_retry_delay = retry_delay  # type: ignore[attr-defined]
        func._task_timeout = timeout  # type: ignore[attr-defined]
        func._task_driver = driver  # type: ignore[attr-defined] # Store driver override
        func._is_task = True  # type: ignore[attr-defined]

        # Add dispatch() method for convenient dispatching
        @functools.wraps(func)
        async def dispatch_method(*args, **kwargs) -> str:
            """Dispatch this function as a task.

            Can accept task parameters plus optional delay parameter.
            Resolves the appropriate dispatcher based on the task's driver override.

            Example:
                await my_func.dispatch(x=1, y=2)
                await my_func.dispatch(x=1, y=2, delay=60)
            """
            from .dispatcher import get_dispatcher

            # Extract delay from kwargs if present
            delay = kwargs.pop("delay", None)

            # Create task instance
            task_instance = FunctionTask(func, *args, **kwargs)

            # Apply delay if specified
            if delay:
                task_instance.delay(delay)

            # Get dispatcher for this task's driver override (if any)
            # func._task_driver is set by @task decorator
            dispatcher = get_dispatcher(func._task_driver)  # type: ignore[attr-defined]

            # Dispatch the task
            return await dispatcher.dispatch(task_instance)

        # Add callable wrapper that returns task instance for chaining
        @functools.wraps(func)
        def call_wrapper(*args, **kwargs) -> FunctionTask[T]:
            """Create task instance for configuration chaining."""
            return FunctionTask(func, *args, **kwargs)

        func.dispatch = dispatch_method  # type: ignore[attr-defined]
        func.__call__ = call_wrapper  # type: ignore[assignment] # Allow send_email(...).delay(...).dispatch()
        return func  # type: ignore[return-value]

    # Support both @task and @task()
    if callable(_func):
        # Being used as @task (without parentheses)
        # _func is the function being decorated
        return decorator(_func)
    else:
        # Being used as @task(...) (with arguments)
        # Return the decorator function to be called with the function
        return decorator
