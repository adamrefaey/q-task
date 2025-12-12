"""FunctionTask and @task decorator with smart execution routing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import functools
import inspect
from typing import Any, Protocol, TypeGuard, final, overload

from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.tasks.core.base_task import BaseTask


class TaskFunctionProtocol(Protocol):
    """Protocol for @task decorated functions with attached configuration."""

    _task_queue: str
    _task_max_retries: int
    _task_retry_delay: int
    _task_timeout: int | None
    _task_driver: str | BaseDriver | None


def _is_async_callable(func: Callable[..., Any]) -> TypeGuard[Callable[..., Awaitable[Any]]]:
    """Type guard for async callables."""
    return inspect.iscoroutinefunction(func)


@final
class FunctionTask[T](BaseTask[T]):
    """Internal wrapper for @task decorated functions.

    Routes execution based on function type and process flag (async/sync × I/O-bound/CPU-bound).
    Do not subclass; use @task decorator instead.
    """

    @classmethod
    def _get_additional_reserved_names(cls) -> frozenset[str]:
        """FunctionTask reserves func, args, kwargs."""
        return frozenset({"func", "args", "kwargs"})

    def __init__(
        self,
        func: Callable[..., T],
        *args: Any,
        use_process: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize with wrapped function and arguments.

        Args:
            func: Function to wrap
            *args: Positional arguments
            use_process: Whether to use process pool for execution
            **kwargs: Keyword arguments

        Raises:
            ValueError: If kwargs use reserved names
        """
        # Call parent init which handles all validation
        super().__init__(**kwargs)

        # FunctionTask-specific setup
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._use_process = use_process

        # Override config with decorator values
        # FunctionTask config always comes from @task decorator, not class attributes
        self.config.queue = getattr(func, "_task_queue", self.config.queue)
        self.config.max_retries = getattr(func, "_task_max_retries", self.config.max_retries)
        self.config.retry_delay = getattr(func, "_task_retry_delay", self.config.retry_delay)
        self.config.timeout = getattr(func, "_task_timeout", self.config.timeout)
        self.config.driver_override = getattr(func, "_task_driver", self.config.driver_override)

    async def run(self) -> T:
        """Execute via appropriate executor (async/sync × thread/process)."""
        if inspect.iscoroutinefunction(self.func):
            return await self._execute_async()
        return await self._execute_sync()

    async def _execute_async(self) -> T:
        """Execute async function (direct await or via process pool)."""
        if self._use_process:
            return await self._execute_async_process()
        return await self._execute_async_direct()

    async def _execute_async_direct(self) -> T:
        """Execute async function via direct await (I/O-bound path)."""
        if not _is_async_callable(self.func):
            raise TypeError(f"Expected async function, got {type(self.func).__name__}")

        # Type checker now knows self.func is Callable[..., Awaitable[Any]]
        return await self.func(*self.args, **self.kwargs)

    async def _execute_async_process(self) -> T:
        """Execute async function via subprocess with asyncio.run() (CPU-bound path)."""
        if not _is_async_callable(self.func):
            raise TypeError(f"Expected async function, got {type(self.func).__name__}")

        from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

        pool = ProcessPoolManager.get_async_pool()
        loop = asyncio.get_running_loop()

        # Capture func for closure (type checker already narrowed it)
        async_func = self.func
        args = self.args
        kwargs = self.kwargs

        def run_in_subprocess():
            # Create wrapper inside subprocess
            async def async_wrapper():
                return await async_func(*args, **kwargs)

            return asyncio.run(async_wrapper())

        return await loop.run_in_executor(pool, run_in_subprocess)

    async def _execute_sync(self) -> T:
        """Execute sync function via thread pool or process pool."""
        loop = asyncio.get_running_loop()
        partial_func = functools.partial(self.func, *self.args, **self.kwargs)

        if self._use_process:
            return await self._execute_sync_process(partial_func, loop)
        return await self._execute_sync_thread(partial_func, loop)

    async def _execute_sync_thread(
        self, func: Callable[[], T], loop: asyncio.AbstractEventLoop
    ) -> T:
        """Execute sync function via ThreadPoolExecutor (I/O-bound path)."""
        return await loop.run_in_executor(None, func)

    async def _execute_sync_process(
        self, func: Callable[[], T], loop: asyncio.AbstractEventLoop
    ) -> T:
        """Execute sync function via ProcessPoolExecutor (CPU-bound path)."""
        from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

        pool = ProcessPoolManager.get_sync_pool()
        return await loop.run_in_executor(pool, func)


class TaskFunction[T](Protocol):
    """Protocol for @task decorated function with dispatch method."""

    __name__: str
    __doc__: str | None

    async def dispatch(self, *args: Any, **kwargs: Any) -> str:
        """Dispatch function as task.

        Returns:
            Task ID
        """
        ...

    def __call__(self, *args: Any, **kwargs: Any) -> FunctionTask[T]:
        """Create task instance for configuration chaining.

        Returns:
            FunctionTask instance
        """
        ...


@overload
def task[T](_func: Callable[..., T], /) -> TaskFunction[T]:
    """@task without arguments."""
    ...


@overload
def task[T](
    _func: None = None,
    /,
    *,
    queue: str = "default",
    max_retries: int = 3,
    retry_delay: int = 60,
    timeout: int | None = None,
    driver: str | BaseDriver | None = None,
    process: bool = False,
) -> Callable[[Callable[..., T]], TaskFunction[T]]:
    """@task with keyword arguments."""
    ...


def task[T](
    _func: Callable[..., T] | None = None,
    /,
    *,
    queue: str = "default",
    max_retries: int = 3,
    retry_delay: int = 60,
    timeout: int | None = None,
    driver: str | BaseDriver | None = None,
    process: bool = False,
) -> TaskFunction[T] | Callable[[Callable[..., T]], TaskFunction[T]]:
    """Decorator to mark function as task.

    Args:
        queue: Queue name (default: "default")
        max_retries: Max retry attempts (default: 3)
        retry_delay: Retry delay in seconds (default: 60)
        timeout: Task timeout in seconds (default: None)
        driver: Driver override (default: None)
        process: Use process pool for CPU-bound work (default: False)

    Returns:
        Decorated function with dispatch() method

    Example:
        ```python
        @task
        async def process_data(data: str) -> str:
            return data.upper()

        @task(queue="emails", process=True)
        def heavy_computation(x: int) -> int:
            return sum(range(x))
        ```
    """

    def decorator(func: Callable[..., T]) -> TaskFunction[T]:
        # Store task configuration on function
        func._task_queue = queue  # type: ignore[attr-defined]
        func._task_max_retries = max_retries  # type: ignore[attr-defined]
        func._task_retry_delay = retry_delay  # type: ignore[attr-defined]
        func._task_timeout = timeout  # type: ignore[attr-defined]
        func._task_driver = driver  # type: ignore[attr-defined]
        func._task_process = process  # type: ignore[attr-defined]
        func._is_task = True  # type: ignore[attr-defined]

        # Add dispatch() method for convenient dispatching
        @functools.wraps(func)
        async def dispatch_method(*args, **kwargs) -> str:
            """Dispatch function as task (supports optional delay parameter)."""
            from asynctasq.core.dispatcher import get_dispatcher

            # Extract delay from kwargs if present
            delay = kwargs.pop("delay", None)

            # Create task instance with process flag
            task_instance = FunctionTask(
                func,
                *args,
                use_process=func._task_process,  # type: ignore[attr-defined]
                **kwargs,
            )

            # Apply delay if specified
            if delay:
                task_instance.delay(delay)

            # Get dispatcher for this task's driver override (if any)
            dispatcher = get_dispatcher(func._task_driver)  # type: ignore[attr-defined]

            # Dispatch the task
            return await dispatcher.dispatch(task_instance)

        # Add callable wrapper that returns task instance for chaining
        @functools.wraps(func)
        def call_wrapper(*args, **kwargs) -> FunctionTask[T]:
            """Create task instance for configuration chaining."""
            return FunctionTask(
                func,
                *args,
                use_process=func._task_process,  # type: ignore[attr-defined]
                **kwargs,
            )

        func.dispatch = dispatch_method  # type: ignore[attr-defined]
        func.__call__ = call_wrapper  # type: ignore[assignment]
        return func  # type: ignore[return-value]

    # Support both @task and @task()
    if callable(_func):
        # Being used as @task (without parentheses)
        return decorator(_func)
    else:
        # Being used as @task(...) (with arguments)
        return decorator
