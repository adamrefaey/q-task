"""Unit tests for SyncTask class.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock external dependencies
- Fast, isolated tests
"""

from unittest.mock import AsyncMock, patch

import pytest

from asynctasq.tasks import SyncTask


class SimpleSyncTask(SyncTask[str]):
    """Concrete SyncTask for testing."""

    def execute(self) -> str:
        """Return a simple string."""
        return "sync_result"


class SyncTaskWithParams(SyncTask[dict]):
    """SyncTask that uses parameters."""

    user_id: int
    filename: str

    def execute(self) -> dict:
        """Return task parameters as dict."""
        return {"user_id": self.user_id, "filename": self.filename}


class SyncTaskWithIO(SyncTask[str]):
    """SyncTask that simulates blocking I/O."""

    path: str

    def execute(self) -> str:
        """Simulate blocking file read."""
        # Simulate synchronous I/O operation
        import time

        time.sleep(0.01)
        return f"read:{self.path}"


class FailingSyncTask(SyncTask[None]):
    """SyncTask that always fails."""

    def execute(self) -> None:
        """Raise an exception."""
        raise OSError("File not found")


class SyncTaskWithFailedHook(SyncTask[None]):
    """SyncTask with custom failed() hook."""

    failure_count: int = 0

    def execute(self) -> None:
        """Raise an exception."""
        raise RuntimeError("Test error")

    async def failed(self, exception: Exception) -> None:
        """Track failures."""
        self.failure_count += 1


class SyncTaskWithRetryLogic(SyncTask[str]):
    """SyncTask with custom retry logic."""

    attempt_number: int = 0

    def execute(self) -> str:
        """Fail on first attempt, succeed on second."""
        self.attempt_number += 1
        if self.attempt_number == 1:
            raise TimeoutError("Request timeout")
        return "success"

    def should_retry(self, exception: Exception) -> bool:
        """Only retry TimeoutError."""
        return isinstance(exception, TimeoutError)


@pytest.mark.unit
class TestSyncTaskBasics:
    """Test basic SyncTask functionality."""

    @pytest.mark.asyncio
    async def test_sync_task_execute_calls_handle_in_thread(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act
        result = await task.run()

        # Assert
        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_sync_task_with_parameters(self) -> None:
        # Arrange
        task = SyncTaskWithParams(user_id=456, filename="data.csv")

        # Act
        result = await task.run()

        # Assert
        assert result == {"user_id": 456, "filename": "data.csv"}

    @pytest.mark.asyncio
    async def test_sync_task_io_simulation(self) -> None:
        # Arrange
        task = SyncTaskWithIO(path="/tmp/test.txt")

        # Act
        result = await task.run()

        # Assert
        assert result == "read:/tmp/test.txt"

    @pytest.mark.asyncio
    async def test_sync_task_raises_exception(self) -> None:
        # Arrange
        task = FailingSyncTask()

        # Act & Assert
        with pytest.raises(IOError, match="File not found"):
            await task.run()

    @pytest.mark.asyncio
    async def test_sync_task_runs_in_thread_pool(self) -> None:
        # Arrange
        import threading

        main_thread_id = threading.get_ident()

        class ThreadCheckTask(SyncTask[tuple[int, bool]]):
            def execute(self) -> tuple[int, bool]:
                task_thread_id = threading.get_ident()
                return (task_thread_id, task_thread_id != main_thread_id)

        task = ThreadCheckTask()

        # Act
        thread_id, is_different = await task.run()

        # Assert
        assert is_different, "SyncTask should run in a different thread"
        assert thread_id != main_thread_id


@pytest.mark.unit
class TestSyncTaskConfiguration:
    """Test SyncTask configuration and chaining."""

    def test_sync_task_default_configuration(self) -> None:
        # Arrange & Act
        task = SimpleSyncTask()

        # Assert
        assert task.config.queue == "default"
        assert task.config.max_retries == 3
        assert task.config.retry_delay == 60
        assert task.config.timeout is None

    def test_sync_task_custom_configuration(self) -> None:
        # Arrange
        class CustomSyncTask(SyncTask[str]):
            queue = "background"
            max_retries = 10
            retry_delay = 30
            timeout = 600

            def execute(self) -> str:
                return "custom"

        # Act
        task = CustomSyncTask()

        # Assert
        assert task.config.queue == "background"
        assert task.config.max_retries == 10
        assert task.config.retry_delay == 30
        assert task.config.timeout == 600

    def test_sync_task_on_queue_chaining(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act
        result = task.on_queue("files")

        # Assert
        assert result is task  # Method chaining returns self
        assert task.config.queue == "files"

    def test_sync_task_delay_chaining(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act
        result = task.delay(90)

        # Assert
        assert result is task
        assert task._delay_seconds == 90

    def test_sync_task_retry_after_chaining(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act
        result = task.retry_after(15)

        # Assert
        assert result is task
        assert task.config.retry_delay == 15

    def test_sync_task_method_chaining_multiple(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act
        result = task.on_queue("low-priority").delay(120).retry_after(60)

        # Assert
        assert result is task
        assert task.config.queue == "low-priority"
        assert task._delay_seconds == 120
        assert task.config.retry_delay == 60


@pytest.mark.unit
class TestSyncTaskLifecycleHooks:
    """Test SyncTask lifecycle hooks (failed, should_retry)."""

    @pytest.mark.asyncio
    async def test_sync_task_failed_hook_callable(self) -> None:
        # Arrange
        task = SyncTaskWithFailedHook()
        task.failure_count = 0

        # Assert - hook exists and is callable
        assert hasattr(task, "failed")
        assert callable(task.failed)

    def test_sync_task_should_retry_default(self) -> None:
        # Arrange
        task = SimpleSyncTask()
        exception = OSError("disk error")

        # Act
        result = task.should_retry(exception)

        # Assert
        assert result is True  # Default is always retry

    def test_sync_task_should_retry_custom(self) -> None:
        # Arrange
        task = SyncTaskWithRetryLogic()

        # Act & Assert - should retry TimeoutError
        assert task.should_retry(TimeoutError("timeout")) is True
        # Should not retry other exceptions
        assert task.should_retry(OSError("other")) is False


@pytest.mark.unit
class TestSyncTaskDispatch:
    """Test SyncTask.dispatch() method."""

    @pytest.mark.asyncio
    async def test_sync_task_dispatch_calls_dispatcher(self) -> None:
        # Arrange
        task = SimpleSyncTask()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = "task-sync-123"

        # Act
        with patch("asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher):
            task_id = await task.dispatch()

        # Assert
        assert task_id == "task-sync-123"
        mock_dispatcher.dispatch.assert_called_once_with(task)

    @pytest.mark.asyncio
    async def test_sync_task_dispatch_with_driver_override(self) -> None:
        # Arrange
        task = SimpleSyncTask()
        task.config.driver_override = "postgres"
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = "task-sync-456"

        # Act
        with patch(
            "asynctasq.core.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ) as mock_get:
            task_id = await task.dispatch()

        # Assert
        assert task_id == "task-sync-456"
        mock_get.assert_called_once_with("postgres")
        mock_dispatcher.dispatch.assert_called_once_with(task)


@pytest.mark.unit
class TestSyncTaskMetadata:
    """Test SyncTask internal metadata management."""

    def test_sync_task_initial_metadata(self) -> None:
        # Arrange & Act
        task = SimpleSyncTask()

        # Assert
        assert task._task_id is None
        assert task._attempts == 0
        assert task._dispatched_at is None

    def test_sync_task_metadata_mutable(self) -> None:
        # Arrange
        task = SimpleSyncTask()
        from datetime import UTC, datetime

        # Act
        task._task_id = "sync-test-id-999"
        task._attempts = 3
        task._dispatched_at = datetime.now(UTC)

        # Assert
        assert task._task_id == "sync-test-id-999"
        assert task._attempts == 3
        assert task._dispatched_at is not None


@pytest.mark.unit
class TestSyncTaskThreadPool:
    """Test SyncTask ThreadPoolExecutor behavior."""

    @pytest.mark.asyncio
    async def test_sync_task_uses_default_executor(self) -> None:
        # Arrange
        task = SimpleSyncTask()

        # Act & Assert - should not raise and complete successfully
        result = await task.run()
        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_sync_task_concurrent_execution(self) -> None:
        # Arrange
        import asyncio

        tasks = [SimpleSyncTask() for _ in range(5)]

        # Act - execute multiple sync tasks concurrently
        results = await asyncio.gather(*[task.run() for task in tasks])

        # Assert - all should complete successfully
        assert len(results) == 5
        assert all(r == "sync_result" for r in results)
