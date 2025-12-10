"""Unit tests for FunctionTask and @task decorator.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock dispatcher to avoid real connections
- Fast, isolated tests
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark, raises

from asynctasq.drivers import BaseDriver
from asynctasq.tasks import FunctionTask, task


@mark.unit
class TestFunctionTask:
    """Test FunctionTask class."""

    def test_function_task_init_stores_function_and_args(self) -> None:
        # Arrange
        def test_func(x: int, y: int) -> int:
            return x + y

        # Act
        task_instance = FunctionTask(test_func, 1, 2)

        # Assert
        assert task_instance.func == test_func
        assert task_instance.args == (1, 2)
        assert task_instance.kwargs == {}

    def test_function_task_init_stores_kwargs(self) -> None:
        # Arrange
        def test_func(a: int, b: str = "default") -> str:
            return f"{a}:{b}"

        # Act
        task_instance = FunctionTask(test_func, a=10, b="custom")

        # Assert
        assert task_instance.func == test_func
        assert task_instance.args == ()
        assert task_instance.kwargs == {"a": 10, "b": "custom"}

    def test_function_task_init_extracts_default_config(self) -> None:
        # Arrange
        def test_func() -> None:
            pass

        # Act
        task_instance = FunctionTask(test_func)

        # Assert
        assert task_instance.queue == "default"
        assert task_instance.max_retries == 3
        assert task_instance.retry_delay == 60
        assert task_instance.timeout is None
        assert task_instance._driver_override is None

    def test_function_task_init_extracts_decorator_config(self) -> None:
        # Arrange
        @task(queue="custom", max_retries=5, retry_delay=120, timeout=300)
        def test_func() -> None:
            pass

        # Act
        task_instance = FunctionTask(test_func)

        # Assert
        assert task_instance.queue == "custom"
        assert task_instance.max_retries == 5
        assert task_instance.retry_delay == 120
        assert task_instance.timeout == 300

    def test_function_task_init_extracts_driver_override(self) -> None:
        # Arrange
        @task(driver="redis")
        def test_func() -> None:
            pass

        # Act
        task_instance = FunctionTask(test_func)

        # Assert
        assert task_instance._driver_override == "redis"

    @mark.asyncio
    async def test_function_task_handle_async_function(self) -> None:
        # Arrange
        async def async_func(x: int) -> int:
            return x * 2

        task_instance = FunctionTask(async_func, 5)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 10

    @mark.asyncio
    async def test_function_task_handle_sync_function(self) -> None:
        # Arrange
        def sync_func(x: int) -> int:
            return x * 3

        task_instance = FunctionTask(sync_func, 4)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 12

    @mark.asyncio
    async def test_function_task_handle_with_kwargs(self) -> None:
        # Arrange
        async def async_func(a: int, b: str) -> str:
            return f"{a}:{b}"

        task_instance = FunctionTask(async_func, a=10, b="test")

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "10:test"

    @mark.asyncio
    async def test_function_task_handle_with_args_and_kwargs(self) -> None:
        # Arrange
        def sync_func(x: int, y: int, z: int = 0) -> int:
            return x + y + z

        task_instance = FunctionTask(sync_func, 1, 2, z=3)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 6

    @mark.asyncio
    async def test_function_task_handle_sync_function_in_executor(self) -> None:
        # Arrange
        def blocking_func() -> str:
            # Simulate blocking operation
            return "blocking_result"

        task_instance = FunctionTask(blocking_func)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "blocking_result"

    @mark.asyncio
    async def test_function_task_handle_with_exception(self) -> None:
        # Arrange
        def failing_func() -> None:
            raise ValueError("test error")

        task_instance = FunctionTask(failing_func)

        # Act & Assert
        with raises(ValueError, match="test error"):
            await task_instance.handle()

    @mark.asyncio
    async def test_function_task_handle_async_with_exception(self) -> None:
        # Arrange
        async def failing_async_func() -> None:
            raise ValueError("async error")

        task_instance = FunctionTask(failing_async_func)

        # Act & Assert
        with raises(ValueError, match="async error"):
            await task_instance.handle()

    def test_function_task_with_no_attributes(self) -> None:
        # Arrange
        def test_func() -> None:
            pass

        # Act
        task_instance = FunctionTask(test_func)

        # Assert
        # Should use defaults when attributes don't exist
        assert task_instance.queue == "default"
        assert task_instance.max_retries == 3


@mark.unit
class TestTaskDecorator:
    """Test @task decorator."""

    def test_task_decorator_without_params(self) -> None:
        # Arrange & Act
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func() -> str:
            return "test"

        # Assert
        assert hasattr(test_func, "_is_task")
        assert test_func._is_task is True  # type: ignore[attr-defined]
        assert test_func._task_queue == "default"  # type: ignore[attr-defined]
        assert test_func._task_max_retries == 3  # type: ignore[attr-defined]

    def test_task_decorator_with_params(self) -> None:
        # Arrange & Act
        @task(queue="custom", max_retries=5, retry_delay=120, timeout=300)
        def test_func() -> str:
            return "test"

        # Assert
        assert test_func._task_queue == "custom"  # type: ignore[attr-defined]
        assert test_func._task_max_retries == 5  # type: ignore[attr-defined]
        assert test_func._task_retry_delay == 120  # type: ignore[attr-defined]
        assert test_func._task_timeout == 300  # type: ignore[attr-defined]

    def test_task_decorator_with_driver_string(self) -> None:
        # Arrange & Act
        @task(driver="sqs")
        def test_func() -> str:
            return "test"

        # Assert
        assert test_func._task_driver == "sqs"  # type: ignore[attr-defined]

    def test_task_decorator_with_driver_instance(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        @task(driver=mock_driver)
        def test_func() -> str:
            return "test"

        # Assert
        assert test_func._task_driver is mock_driver  # type: ignore[attr-defined]

    def test_task_decorator_adds_dispatch_method(self) -> None:
        # Arrange & Act
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        # Assert
        assert hasattr(test_func, "dispatch")
        # Use cast to access dynamically added attributes
        func_any = cast(Any, test_func)
        assert callable(func_any.dispatch)

    def test_task_decorator_adds_call_wrapper(self) -> None:
        # Arrange & Act
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        # Act - __call__ is set but Python's function call mechanism doesn't use it
        # So calling the function directly executes it, not the wrapper
        # To get a FunctionTask, we need to use the __call__ attribute explicitly
        # or create it manually. For chaining, use: test_func(5).delay(60).dispatch()
        # which works because the function returns a value that can be chained
        # Actually, the __call__ wrapper is meant for method chaining, but
        # Python's function call doesn't use __call__ for functions.
        # So we test that __call__ exists and can be used explicitly
        assert callable(test_func)
        # Using __call__ explicitly should work
        # Use cast to access dynamically added attributes
        func_any = cast(Any, test_func)
        task_instance = func_any.__call__(5)

        # Assert
        assert isinstance(task_instance, FunctionTask)
        assert task_instance.func == test_func
        assert task_instance.args == (5,)

    @mark.asyncio
    async def test_task_decorator_dispatch_method(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-123")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            task_id = await func_any.dispatch(x=10)

            # Assert
            assert task_id == "task-id-123"
            mock_dispatcher.dispatch.assert_called_once()
            # Verify FunctionTask was created with correct args
            call_args = mock_dispatcher.dispatch.call_args[0][0]
            assert isinstance(call_args, FunctionTask)
            assert call_args.func == test_func

    @mark.asyncio
    async def test_task_decorator_dispatch_with_delay(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-delayed")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            task_id = await func_any.dispatch(x=10, delay=60)

            # Assert
            assert task_id == "task-id-delayed"
            # Verify delay was set on task instance
            call_args = mock_dispatcher.dispatch.call_args[0][0]
            assert isinstance(call_args, FunctionTask)
            assert call_args._delay_seconds == 60

    @mark.asyncio
    async def test_task_decorator_dispatch_with_driver_override(self) -> None:
        # Arrange
        @task(driver="redis")
        def test_func() -> None:
            pass

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-driver")

        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            await func_any.dispatch()

            # Assert
            mock_get.assert_called_once_with("redis")

    @mark.asyncio
    async def test_task_decorator_chaining_delay_dispatch(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-chained")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act - Use __call__ explicitly to get FunctionTask for chaining
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            task_id = await func_any.__call__(x=10).delay(120).dispatch()

            # Assert
            assert task_id == "task-id-chained"
            call_args = mock_dispatcher.dispatch.call_args[0][0]
            assert isinstance(call_args, FunctionTask)
            assert call_args._delay_seconds == 120

    def test_task_decorator_preserves_function_metadata(self) -> None:
        # Arrange
        def test_func(x: int) -> int:
            """Test function docstring."""
            return x * 2

        # Act
        decorated = task(test_func)  # type: ignore[arg-type]  # Overload handles callable as first arg

        # Assert
        assert decorated.__name__ == "test_func"
        assert decorated.__doc__ == "Test function docstring."

    def test_task_decorator_with_multiple_functions(self) -> None:
        # Arrange & Act
        @task(queue="queue1")
        def func1() -> None:
            pass

        @task(queue="queue2")
        def func2() -> None:
            pass

        # Assert
        assert func1._task_queue == "queue1"  # type: ignore[attr-defined]
        assert func2._task_queue == "queue2"  # type: ignore[attr-defined]

    def test_task_decorator_call_wrapper_creates_function_task(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(a: int, b: str) -> str:
            return f"{a}:{b}"

        # Act - Use __call__ explicitly since Python's function call doesn't use __call__
        # Use cast to access dynamically added attributes
        func_any = cast(Any, test_func)
        task_instance = func_any.__call__(1, b="test")

        # Assert
        assert isinstance(task_instance, FunctionTask)
        assert task_instance.args == (1,)
        assert task_instance.kwargs == {"b": "test"}

    @mark.asyncio
    async def test_task_decorator_dispatch_extracts_delay_from_kwargs(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            await func_any.dispatch(x=5, delay=180)

            # Assert
            # delay should be removed from kwargs and not passed to function
            call_args = mock_dispatcher.dispatch.call_args[0][0]
            assert isinstance(call_args, FunctionTask)
            # The function kwargs should not contain 'delay'
            assert "delay" not in call_args.kwargs
            assert call_args._delay_seconds == 180

    def test_task_decorator_callable_check(self) -> None:
        # Arrange
        def test_func() -> None:
            pass

        # Act - decorator should handle callable directly
        decorated = task(test_func)  # type: ignore[arg-type]  # Overload handles callable as first arg

        # Assert
        assert callable(decorated)
        assert hasattr(decorated, "_is_task")

    def test_task_decorator_with_none_driver(self) -> None:
        # Arrange & Act
        @task(driver=None)
        def test_func() -> None:
            pass

        # Assert
        assert test_func._task_driver is None  # type: ignore[attr-defined]

    def test_task_decorator_with_timeout_none(self) -> None:
        # Arrange & Act
        @task(timeout=None)
        def test_func() -> None:
            pass

        # Assert
        assert test_func._task_timeout is None  # type: ignore[attr-defined]


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
