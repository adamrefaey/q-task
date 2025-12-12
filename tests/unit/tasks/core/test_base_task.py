"""Unit tests for AsyncTask module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock dispatcher to avoid real connections
- Fast, isolated tests
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark

from asynctasq.drivers import BaseDriver
from asynctasq.tasks import AsyncTask


# Test implementations for abstract AsyncTask
class ConcreteTask(AsyncTask[str]):
    """Concrete implementation of AsyncTask for testing."""

    async def execute(self) -> str:
        """Test implementation."""
        return "success"


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
        assert hasattr(task_instance, "config")
        assert task_instance.config.queue == "default"

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
        class CustomTask(AsyncTask[str]):
            queue = "custom_queue"
            max_retries = 5

            async def execute(self) -> str:
                return "test"

        # Act
        task_instance = CustomTask()

        # Assert - class attributes should be preserved
        assert task_instance.config.queue == "custom_queue"
        assert task_instance.config.max_retries == 5


@mark.unit
class TestTaskConfiguration:
    """Test Task configuration attributes."""

    def test_default_queue(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.config.queue == "default"

    def test_default_max_retries(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.config.max_retries == 3

    def test_default_retry_delay(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.config.retry_delay == 60

    def test_default_timeout(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.config.timeout is None

    def test_default_driver_override(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance.config.driver_override is None

    def test_default_delay_seconds(self) -> None:
        # Act
        task_instance = ConcreteTask()

        # Assert
        assert task_instance._delay_seconds is None

    def test_custom_configuration(self) -> None:
        # Arrange
        class CustomTask(AsyncTask[str]):
            queue = "high_priority"
            max_retries = 10
            retry_delay = 120
            timeout = 300

            async def execute(self) -> str:
                return "test"

        # Act
        task_instance = CustomTask()

        # Assert
        assert task_instance.config.queue == "high_priority"
        assert task_instance.config.max_retries == 10
        assert task_instance.config.retry_delay == 120
        assert task_instance.config.timeout == 300


@mark.unit
class TestTaskExecute:
    """Test Task.execute() abstract method."""

    @mark.asyncio
    async def test_execute_implementation(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = await task_instance.execute()

        # Assert
        assert result == "success"


@mark.unit
class TestTaskFailed:
    """Test Task.failed() method."""

    @mark.asyncio
    async def test_failed_default_implementation(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        exception = ValueError("test error")

        # Act & Assert - should not raise
        await task_instance.failed(exception)

    @mark.asyncio
    async def test_failed_custom_implementation(self) -> None:
        # Arrange
        failed_called = False

        class CustomFailedTask(AsyncTask[str]):
            async def execute(self) -> str:
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
        class CustomRetryTask(AsyncTask[str]):
            async def execute(self) -> str:
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
        assert task_instance.config.queue == "high_priority"
        assert result is task_instance  # Returns self for chaining

    def test_on_queue_method_chaining(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("custom").on_queue("another")

        # Assert
        assert task_instance.config.queue == "another"
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
        assert task_instance.config.retry_delay == 180
        assert result is task_instance  # Returns self for chaining

    def test_retry_after_method_chaining(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.retry_after(60).retry_after(120)

        # Assert
        assert task_instance.config.retry_delay == 120
        assert result is task_instance

    def test_retry_after_with_zero(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        task_instance.retry_after(0)

        # Assert
        assert task_instance.config.retry_delay == 0


@mark.unit
class TestTaskDispatch:
    """Test Task.dispatch() method."""

    @mark.asyncio
    async def test_dispatch_calls_get_dispatcher(self) -> None:
        # Arrange
        # Import AsyncTask to ensure it's available when dispatcher is imported
        from asynctasq.tasks import AsyncTask  # noqa: F401

        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-123")

        # Patch at the dispatcher module level (where it's defined)
        # This works because the import inside dispatch() will use the patched version
        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            task_id = await task_instance.dispatch()

            # Assert
            assert task_id == "task-id-123"
            mock_dispatcher.dispatch.assert_called_once_with(task_instance)

    @mark.asyncio
    async def test_dispatch_with_driver_override_string(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        task_instance.config.driver_override = "redis"
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-456")

        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with("redis")

    @mark.asyncio
    async def test_dispatch_with_driver_override_instance(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_driver = MagicMock(spec=BaseDriver)
        task_instance.config.driver_override = mock_driver
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-789")

        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with(mock_driver)

    @mark.asyncio
    async def test_dispatch_with_no_driver_override(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-default")

        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            # Act
            await task_instance.dispatch()

            # Assert
            mock_get.assert_called_once_with(None)

    @mark.asyncio
    async def test_dispatch_with_delay_configured(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        task_instance.delay(300)
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="task-id-delayed")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # Delay should be passed through dispatcher
            mock_dispatcher.dispatch.assert_called_once()


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

    @mark.asyncio
    async def test_task_dispatch_sets_task_id(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="test-task-id")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # The dispatcher sets _task_id internally, but we can verify it was called
            mock_dispatcher.dispatch.assert_called_once()

    @mark.asyncio
    async def test_task_dispatch_sets_dispatched_at(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value="test-task-id")

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            # Act
            await task_instance.dispatch()

            # Assert
            # The dispatcher sets _dispatched_at internally
            mock_dispatcher.dispatch.assert_called_once()

    def test_task_retry_after_changes_retry_delay(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        original_delay = task_instance.config.retry_delay

        # Act
        task_instance.retry_after(200)

        # Assert
        assert task_instance.config.retry_delay == 200
        assert task_instance.config.retry_delay != original_delay

    def test_task_on_queue_changes_queue(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        original_queue = task_instance.config.queue

        # Act
        task_instance.on_queue("new_queue")

        # Assert
        assert task_instance.config.queue == "new_queue"
        assert task_instance.config.queue != original_queue

    @mark.asyncio
    async def test_task_dispatch_chain_with_multiple_calls(self) -> None:
        # Arrange
        task_instance = ConcreteTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=["id1", "id2", "id3"])

        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
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
        assert task_instance.config.queue == "custom"
        assert task_instance._delay_seconds == 120
        assert result is task_instance

    def test_delay_retry_after_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.delay(60).retry_after(180)

        # Assert
        assert task_instance._delay_seconds == 60
        assert task_instance.config.retry_delay == 180
        assert result is task_instance

    def test_on_queue_retry_after_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("high").retry_after(240)

        # Assert
        assert task_instance.config.queue == "high"
        assert task_instance.config.retry_delay == 240
        assert result is task_instance

    def test_complex_chain(self) -> None:
        # Arrange
        task_instance = ConcreteTask()

        # Act
        result = task_instance.on_queue("priority").delay(300).retry_after(120).on_queue("final")

        # Assert
        assert task_instance.config.queue == "final"
        assert task_instance._delay_seconds == 300
        assert task_instance.config.retry_delay == 120
        assert result is task_instance


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
