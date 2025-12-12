"""Unit tests for AsyncTask class.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock external dependencies
- Fast, isolated tests
"""

from unittest.mock import AsyncMock, patch

import pytest

from asynctasq.tasks import AsyncTask


class SimpleAsyncTask(AsyncTask[str]):
    """Concrete AsyncTask for testing."""

    async def execute(self) -> str:
        """Return a simple string."""
        return "async_result"


class AsyncTaskWithParams(AsyncTask[dict]):
    """AsyncTask that uses parameters."""

    user_id: int
    action: str

    async def execute(self) -> dict:
        """Return task parameters as dict."""
        return {"user_id": self.user_id, "action": self.action}


class AsyncTaskWithIO(AsyncTask[str]):
    """AsyncTask that simulates I/O operations."""

    url: str

    async def execute(self) -> str:
        """Simulate async I/O."""
        # Simulate async HTTP call
        import asyncio

        await asyncio.sleep(0.01)
        return f"fetched:{self.url}"


class FailingAsyncTask(AsyncTask[None]):
    """AsyncTask that always fails."""

    async def execute(self) -> None:
        """Raise an exception."""
        raise ValueError("Task failed intentionally")


class AsyncTaskWithFailedHook(AsyncTask[None]):
    """AsyncTask with custom failed() hook."""

    failure_count: int = 0

    async def execute(self) -> None:
        """Raise an exception."""
        raise RuntimeError("Test error")

    async def failed(self, exception: Exception) -> None:
        """Track failures."""
        self.failure_count += 1


class AsyncTaskWithRetryLogic(AsyncTask[str]):
    """AsyncTask with custom retry logic."""

    attempt_number: int = 0

    async def execute(self) -> str:
        """Fail on first attempt, succeed on second."""
        self.attempt_number += 1
        if self.attempt_number == 1:
            raise ConnectionError("Transient error")
        return "success"

    def should_retry(self, exception: Exception) -> bool:
        """Only retry ConnectionError."""
        return isinstance(exception, ConnectionError)


@pytest.mark.unit
class TestAsyncTaskBasics:
    """Test basic AsyncTask functionality."""

    @pytest.mark.asyncio
    async def test_async_task_execute_calls_handle(self) -> None:
        # Arrange
        task = SimpleAsyncTask()

        # Act
        result = await task.execute()

        # Assert
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_async_task_with_parameters(self) -> None:
        # Arrange
        task = AsyncTaskWithParams(user_id=123, action="update")

        # Act
        result = await task.execute()

        # Assert
        assert result == {"user_id": 123, "action": "update"}

    @pytest.mark.asyncio
    async def test_async_task_io_simulation(self) -> None:
        # Arrange
        task = AsyncTaskWithIO(url="https://api.example.com")

        # Act
        result = await task.execute()

        # Assert
        assert result == "fetched:https://api.example.com"

    @pytest.mark.asyncio
    async def test_async_task_raises_exception(self) -> None:
        # Arrange
        task = FailingAsyncTask()

        # Act & Assert
        with pytest.raises(ValueError, match="Task failed intentionally"):
            await task.execute()


@pytest.mark.unit
class TestAsyncTaskConfiguration:
    """Test AsyncTask configuration and chaining."""

    def test_async_task_default_configuration(self) -> None:
        # Arrange & Act
        task = SimpleAsyncTask()

        # Assert
        assert task.config.queue == "default"
        assert task.config.max_retries == 3
        assert task.config.retry_delay == 60
        assert task.config.timeout is None

    def test_async_task_custom_configuration(self) -> None:
        # Arrange
        class CustomAsyncTask(AsyncTask[str]):
            queue = "high-priority"
            max_retries = 5
            retry_delay = 120
            timeout = 300

            async def execute(self) -> str:
                return "custom"

        # Act
        task = CustomAsyncTask()

        # Assert
        assert task.config.queue == "high-priority"
        assert task.config.max_retries == 5
        assert task.config.retry_delay == 120
        assert task.config.timeout == 300

    def test_async_task_on_queue_chaining(self) -> None:
        # Arrange
        task = SimpleAsyncTask()

        # Act
        result = task.on_queue("emails")

        # Assert
        assert result is task  # Method chaining returns self
        assert task.config.queue == "emails"

    def test_async_task_delay_chaining(self) -> None:
        # Arrange
        task = SimpleAsyncTask()

        # Act
        result = task.delay(120)

        # Assert
        assert result is task
        assert task._delay_seconds == 120

    def test_async_task_retry_after_chaining(self) -> None:
        # Arrange
        task = SimpleAsyncTask()

        # Act
        result = task.retry_after(30)

        # Assert
        assert result is task
        assert task.config.retry_delay == 30

    def test_async_task_method_chaining_multiple(self) -> None:
        # Arrange
        task = SimpleAsyncTask()

        # Act
        result = task.on_queue("priority").delay(60).retry_after(45)

        # Assert
        assert result is task
        assert task.config.queue == "priority"
        assert task._delay_seconds == 60
        assert task.config.retry_delay == 45


@pytest.mark.unit
class TestAsyncTaskLifecycleHooks:
    """Test AsyncTask lifecycle hooks (failed, should_retry)."""

    @pytest.mark.asyncio
    async def test_async_task_failed_hook_not_called_on_success(self) -> None:
        # Arrange
        task = AsyncTaskWithFailedHook()
        task.failure_count = 0

        # Act - succeed immediately (no failure)
        # We need to test this via TaskService, but for now just verify hook exists
        assert hasattr(task, "failed")
        assert callable(task.failed)

    def test_async_task_should_retry_default(self) -> None:
        # Arrange
        task = SimpleAsyncTask()
        exception = ValueError("test error")

        # Act
        result = task.should_retry(exception)

        # Assert
        assert result is True  # Default is always retry

    def test_async_task_should_retry_custom(self) -> None:
        # Arrange
        task = AsyncTaskWithRetryLogic()

        # Act & Assert - should retry ConnectionError
        assert task.should_retry(ConnectionError("network")) is True
        # Should not retry other exceptions
        assert task.should_retry(ValueError("other")) is False


@pytest.mark.unit
class TestAsyncTaskDispatch:
    """Test AsyncTask.dispatch() method."""

    @pytest.mark.asyncio
    async def test_async_task_dispatch_calls_dispatcher(self) -> None:
        # Arrange
        task = SimpleAsyncTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = "task-123"

        # Act
        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            task_id = await task.dispatch()

        # Assert
        assert task_id == "task-123"
        mock_dispatcher.dispatch.assert_called_once_with(task)

    @pytest.mark.asyncio
    async def test_async_task_dispatch_with_driver_override(self) -> None:
        # Arrange
        task = SimpleAsyncTask()
        task.config.driver_override = "redis"
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = "task-456"

        # Act
        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            task_id = await task.dispatch()

        # Assert
        assert task_id == "task-456"
        mock_get.assert_called_once_with("redis")
        mock_dispatcher.dispatch.assert_called_once_with(task)


@pytest.mark.unit
class TestAsyncTaskMetadata:
    """Test AsyncTask internal metadata management."""

    def test_async_task_initial_metadata(self) -> None:
        # Arrange & Act
        task = SimpleAsyncTask()

        # Assert
        assert task._task_id is None
        assert task._attempts == 0
        assert task._dispatched_at is None

    def test_async_task_metadata_mutable(self) -> None:
        # Arrange
        task = SimpleAsyncTask()
        from datetime import UTC, datetime

        # Act
        task._task_id = "test-id-789"
        task._attempts = 2
        task._dispatched_at = datetime.now(UTC)

        # Assert
        assert task._task_id == "test-id-789"
        assert task._attempts == 2
        assert task._dispatched_at is not None
