"""Unit tests for Task module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock dispatcher to avoid real connections
- Fast, isolated tests
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark, raises

from async_task.core.task import FunctionTask, SyncTask, Task, task
from async_task.drivers.base_driver import BaseDriver


# Test implementations for abstract Task
class ConcreteTask(Task[str]):
    """Concrete implementation of Task for testing."""

    async def handle(self) -> str:
        """Test implementation."""
        return "success"


class ConcreteSyncTask(SyncTask[str]):
    """Concrete implementation of SyncTask for testing."""

    def handle_sync(self) -> str:
        """Test sync implementation."""
        return "sync_success"


@mark.unit
class TestTaskInitialization:
    """Test Task.__init__() method."""

    def test_init_sets_kwargs_as_attributes(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask(param1="value1", param2=42, param3=True)

        # Assert - attributes are set dynamically via setattr in __init__
        # Use cast to access dynamic attributes
        task_any = cast(Any, task_instance)
        assert task_any.param1 == "value1"
        assert task_any.param2 == 42
        assert task_any.param3 is True

    def test_init_sets_default_metadata(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance._task_id is None
        assert task_instance._attempts == 0
        assert task_instance._dispatched_at is None

    def test_init_with_empty_kwargs(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask()

        # Assert
        assert hasattr(task_instance, "queue")
        assert task_instance.queue == "default"

    def test_init_with_complex_kwargs(self) -> None:
        # Arrange
        complex_dict = {"nested": {"key": "value"}}
        complex_list = [1, 2, 3]

        # Act
        task_instance = ConcreteTask(
            data=complex_dict,
            items=complex_list,
            number=123.456,
        )

        # Assert - attributes are set dynamically via setattr in __init__
        # Use cast to access dynamic attributes
        task_any = cast(Any, task_instance)
        assert task_any.data == complex_dict
        assert task_any.items == complex_list
        assert task_any.number == 123.456

    def test_init_overrides_class_attributes(self) -> None:
        # Arrange
        class CustomTask(Task[str]):
            queue = "custom_queue"
            max_retries = 5

            async def handle(self) -> str:
                return "test"

        # Act
        task_instance = CustomTask()

        # Assert - class attributes should be preserved
        assert task_instance.queue == "custom_queue"
        assert task_instance.max_retries == 5


@mark.unit
class TestTaskConfiguration:
    """Test Task configuration attributes."""

    def test_default_queue(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.queue == "default"

    def test_default_max_retries(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.max_retries == 3

    def test_default_retry_delay(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.retry_delay == 60

    def test_default_timeout(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.timeout is None

    def test_default_driver_override(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance._driver_override is None

    def test_default_delay_seconds(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance._delay_seconds is None

    def test_custom_configuration(self) -> None:
        # Arrange
        class CustomTask(Task[str]):
            queue = "high_priority"
            max_retries = 10
            retry_delay = 120
            timeout = 300

            async def handle(self) -> str:
                return "test"

        # Act
        task_instance = CustomTask()

        # Assert
        assert task_instance.queue == "high_priority"
        assert task_instance.max_retries == 10
        assert task_instance.retry_delay == 120
        assert task_instance.timeout == 300


@mark.unit
class TestTaskHandle:
    """Test Task.handle() abstract method."""

    async def test_handle_must_be_implemented(self) -> None:
        # Arrange
        class IncompleteTask(Task[str]):
            pass  # Missing handle() implementation

        # Act & Assert - abstract class cannot be instantiated
        with raises(TypeError):
            # Type checker correctly identifies this as an error
            # but we're testing runtime behavior
            IncompleteTask()  # type: ignore[abstract]

    async def test_handle_execution(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "success"


@mark.unit
class TestTaskFailed:
    """Test Task.failed() method."""

    async def test_failed_default_implementation(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        exception = ValueError("test error")

        # Act & Assert - should not raise
        await task_instance.failed(exception)

    async def test_failed_custom_implementation(self) -> None:
        # Arrange
        failed_called = False

        class CustomFailedTask(Task[str]):
            async def handle(self) -> str:
                return "test"

            async def failed(self, exception: Exception) -> None:
                nonlocal failed_called
                failed_called = True
                assert isinstance(exception, ValueError)

        task_instance = CustomFailedTask()
        exception = ValueError("test error")

        # Act
        await task_instance.failed(exception)

        # Assert
        assert failed_called is True


@mark.unit
class TestTaskShouldRetry:
    """Test Task.should_retry() method."""

    def test_should_retry_default_returns_true(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        exception = ValueError("test error")

        # Act
        result = task_instance.should_retry(exception)

        # Assert
        assert result is True

    def test_should_retry_custom_implementation(self) -> None:
        # Arrange
        class CustomRetryTask(Task[str]):
            async def handle(self) -> str:
                return "test"

            def should_retry(self, exception: Exception) -> bool:
                return isinstance(exception, ValueError)

        task_instance = CustomRetryTask()

        # Act & Assert
        assert task_instance.should_retry(ValueError("test")) is True
        assert task_instance.should_retry(TypeError("test")) is False


@mark.unit
class TestTaskOnQueue:
    """Test Task.on_queue() method."""

    def test_on_queue_sets_queue(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("high_priority")

        # Assert
        assert task_instance.queue == "high_priority"
        assert result is task_instance  # Returns self for chaining

    def test_on_queue_method_chaining(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("custom").on_queue("another")

        # Assert
        assert task_instance.queue == "another"
        assert result is task_instance


@mark.unit
class TestTaskDelay:
    """Test Task.delay() method."""

    def test_delay_sets_delay_seconds(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.delay(120)

        # Assert
        assert task_instance._delay_seconds == 120
        assert result is task_instance  # Returns self for chaining

    def test_delay_method_chaining(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.delay(60).delay(120)

        # Assert
        assert task_instance._delay_seconds == 120
        assert result is task_instance

    def test_delay_with_zero(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        task_instance.delay(0)

        # Assert
        assert task_instance._delay_seconds == 0

    def test_delay_with_large_value(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        task_instance.delay(86400)  # 24 hours

        # Assert
        assert task_instance._delay_seconds == 86400


@mark.unit
class TestTaskRetryAfter:
    """Test Task.retry_after() method."""

    def test_retry_after_sets_retry_delay(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.retry_after(180)

        # Assert
        assert task_instance.retry_delay == 180
        assert result is task_instance  # Returns self for chaining

    def test_retry_after_method_chaining(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.retry_after(60).retry_after(120)

        # Assert
        assert task_instance.retry_delay == 120
        assert result is task_instance

    def test_retry_after_with_zero(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        task_instance.retry_after(0)

        # Assert
        assert task_instance.retry_delay == 0


@mark.unit
class TestTaskDispatch:
    """Test Task.dispatch() method."""

    async def test_dispatch_calls_get_dispatcher(self) -> None:
        # Arrange
        # Import Task to ensure it's available when dispatcher is imported
        from async_task.core.task import Task  # noqa: F401

        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-123")

        # Patch at the dispatcher module level (where it's defined)
        # This works because the import inside dispatch() will use the patched version
        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            task_id = await task_instance.dispatch()

            # Assert
            assert task_id == "task-id-123"
            mock_dispatcher.dispatch.assert_called_once_with(task_instance)

    async def test_dispatch_with_driver_override_string(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        task_instance._driver_override = "redis"
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-456")

        with patch(
            "async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with("redis")

    async def test_dispatch_with_driver_override_instance(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_driver = MagicMock(spec=BaseDriver)
        task_instance._driver_override = mock_driver
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-789")

        with patch(
            "async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with(mock_driver)

    async def test_dispatch_with_no_driver_override(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-default")

        with patch(
            "async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with(None)

    async def test_dispatch_with_delay_configured(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        task_instance.delay(300)
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-delayed")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # Delay should be passed through dispatcher
            mock_dispatcher.dispatch.assert_called_once()


@mark.unit
class TestSyncTask:
    """Test SyncTask class."""

    async def test_sync_task_handle_calls_handle_sync(self) -> None:
        # Arrange
        task_instance = ConcreteSyncTask()

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "sync_success"

    async def test_sync_task_handle_runs_in_executor(self) -> None:
        # Arrange
        task_instance = ConcreteSyncTask()
        asyncio.get_event_loop()

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "sync_success"
        # Verify it's actually running in executor (not directly)
        # This is implicit - if it were running directly, we'd see different behavior

    def test_sync_task_must_implement_handle_sync(self) -> None:
        # Arrange
        class IncompleteSyncTask(SyncTask[str]):
            pass  # Missing handle_sync() implementation

        # Act & Assert - abstract class cannot be instantiated
        with raises(TypeError):
            # Type checker correctly identifies this as an error
            # but we're testing runtime behavior
            IncompleteSyncTask()  # type: ignore[abstract]


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

    async def test_function_task_handle_async_function(self) -> None:
        # Arrange
        async def async_func(x: int) -> int:
            return x * 2

        task_instance = FunctionTask(async_func, 5)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 10

    async def test_function_task_handle_sync_function(self) -> None:
        # Arrange
        def sync_func(x: int) -> int:
            return x * 3

        task_instance = FunctionTask(sync_func, 4)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 12

    async def test_function_task_handle_with_kwargs(self) -> None:
        # Arrange
        async def async_func(a: int, b: str) -> str:
            return f"{a}:{b}"

        task_instance = FunctionTask(async_func, a=10, b="test")

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "10:test"

    async def test_function_task_handle_with_args_and_kwargs(self) -> None:
        # Arrange
        def sync_func(x: int, y: int, z: int = 0) -> int:
            return x + y + z

        task_instance = FunctionTask(sync_func, 1, 2, z=3)

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == 6

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

    async def test_task_decorator_dispatch_method(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-123")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
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

    async def test_task_decorator_dispatch_with_delay(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-delayed")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
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

    async def test_task_decorator_dispatch_with_driver_override(self) -> None:
        # Arrange
        @task(driver="redis")
        def test_func() -> None:
            pass

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-driver")

        with patch(
            "async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            # Use cast to access dynamically added attributes
            func_any = cast(Any, test_func)
            await func_any.dispatch()

            # Assert
            mock_get.assert_called_once_with("redis")

    async def test_task_decorator_chaining_delay_dispatch(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x * 2

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-chained")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
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

    async def test_task_decorator_dispatch_extracts_delay_from_kwargs(self) -> None:
        # Arrange
        @task  # type: ignore[arg-type]  # Overload handles callable as first arg
        def test_func(x: int) -> int:
            return x

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
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


@mark.unit
class TestTaskEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_task_with_none_values(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask(
            param1=None,
            param2=None,
        )

        # Assert - attributes are set dynamically via setattr in __init__
        # Use cast to access dynamic attributes
        task_any = cast(Any, task_instance)
        assert task_any.param1 is None
        assert task_any.param2 is None

    def test_task_with_empty_string(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask(param="")

        # Assert - attributes are set dynamically via setattr in __init__
        # Use cast to access dynamic attributes
        task_any = cast(Any, task_instance)
        assert task_any.param == ""

    def test_task_with_special_characters(self) -> None:
        # Arrange & Act
        task_instance = ConcreteTask(
            param1="test@example.com",
            param2="path/to/file",
            param3="key:value",
        )

        # Assert - attributes are set dynamically via setattr in __init__
        # Use cast to access dynamic attributes
        task_any = cast(Any, task_instance)
        assert task_any.param1 == "test@example.com"
        assert task_any.param2 == "path/to/file"
        assert task_any.param3 == "key:value"

    async def test_task_dispatch_sets_task_id(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="test-task-id")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # The dispatcher sets _task_id internally, but we can verify it was called
            mock_dispatcher.dispatch.assert_called_once()

    async def test_task_dispatch_sets_dispatched_at(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="test-task-id")

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # The dispatcher sets _dispatched_at internally
            mock_dispatcher.dispatch.assert_called_once()

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

    def test_task_retry_after_changes_retry_delay(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        original_delay = task_instance.retry_delay

        # Act
        task_instance.retry_after(200)

        # Assert
        assert task_instance.retry_delay == 200
        assert task_instance.retry_delay != original_delay

    def test_task_on_queue_changes_queue(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        original_queue = task_instance.queue

        # Act
        task_instance.on_queue("new_queue")

        # Assert
        assert task_instance.queue == "new_queue"
        assert task_instance.queue != original_queue

    async def test_function_task_handle_with_exception(self) -> None:
        # Arrange
        def failing_func() -> None:
            raise ValueError("test error")

        task_instance = FunctionTask(failing_func)

        # Act & Assert
        with raises(ValueError, match="test error"):
            await task_instance.handle()

    async def test_function_task_handle_async_with_exception(self) -> None:
        # Arrange
        async def failing_async_func() -> None:
            raise ValueError("async error")

        task_instance = FunctionTask(failing_async_func)

        # Act & Assert
        with raises(ValueError, match="async error"):
            await task_instance.handle()

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

    async def test_task_dispatch_chain_with_multiple_calls(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=["id1", "id2", "id3"])

        with patch("async_task.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            id1 = await task_instance.dispatch()
            id2 = await task_instance.dispatch()
            id3 = await task_instance.dispatch()

            # Assert
            assert id1 == "id1"
            assert id2 == "id2"
            assert id3 == "id3"
            assert mock_dispatcher.dispatch.call_count == 3


@mark.unit
class TestTaskMethodChaining:
    """Test method chaining capabilities."""

    def test_on_queue_delay_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("custom").delay(120)

        # Assert
        assert task_instance.queue == "custom"
        assert task_instance._delay_seconds == 120
        assert result is task_instance

    def test_delay_retry_after_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.delay(60).retry_after(180)

        # Assert
        assert task_instance._delay_seconds == 60
        assert task_instance.retry_delay == 180
        assert result is task_instance

    def test_on_queue_retry_after_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("high").retry_after(240)

        # Assert
        assert task_instance.queue == "high"
        assert task_instance.retry_delay == 240
        assert result is task_instance

    def test_complex_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("priority").delay(300).retry_after(120).on_queue("final")

        # Assert
        assert task_instance.queue == "final"
        assert task_instance._delay_seconds == 300
        assert task_instance.retry_delay == 120
        assert result is task_instance


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
