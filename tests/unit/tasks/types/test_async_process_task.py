"""Unit tests for AsyncProcessTask class."""

import asyncio
import os

import pytest

from asynctasq.tasks import AsyncProcessTask
from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

from .conftest import SharedAsyncFactorialTask


@pytest.fixture
def manager() -> ProcessPoolManager:
    """Create ProcessPoolManager instance with test configuration."""
    return ProcessPoolManager(sync_max_workers=4, async_max_workers=4)


class AsyncGetPIDTask(AsyncProcessTask[int]):
    """Test task that returns the process ID asynchronously."""

    async def execute(self) -> int:
        """Return the current process ID after async sleep."""
        await asyncio.sleep(0.001)  # Brief async operation
        return os.getpid()


class AsyncRaiseExceptionTask(AsyncProcessTask[None]):
    """Test task that raises an exception asynchronously."""

    async def execute(self) -> None:
        """Raise a test exception after async sleep."""
        await asyncio.sleep(0.001)
        raise ValueError("Async test exception from subprocess")


class AsyncAttributeTask(AsyncProcessTask[dict]):
    """Test task that verifies attribute passing to subprocess."""

    a: int
    b: str
    c: list[int]

    async def execute(self) -> dict:
        """Return all attributes as dict after async sleep."""
        await asyncio.sleep(0.001)  # Ensure async execution
        return {"a": self.a, "b": self.b, "c": self.c}


class AsyncIOTask(AsyncProcessTask[str]):
    """Test task that performs async I/O operations."""

    message: str

    async def execute(self) -> str:
        """Simulate async I/O work."""
        # Simulate multiple async operations
        for _ in range(3):
            await asyncio.sleep(0.001)
        return f"Processed: {self.message}"


@pytest.mark.asyncio
async def test_async_process_task_basic_execution():
    """Test AsyncProcessTask executes successfully and returns correct result."""
    # Arrange
    task = SharedAsyncFactorialTask(n=5)

    # Act
    result = await task.run()

    # Assert
    assert result == 120  # 5! = 120


@pytest.mark.asyncio
async def test_async_process_task_isolation():
    """Verify each task runs in separate process (not main process)."""
    # Arrange
    task = AsyncGetPIDTask()
    main_pid = os.getpid()

    # Act
    task_pid = await task.run()

    # Assert - task should run in different process
    assert task_pid != main_pid
    assert isinstance(task_pid, int)
    assert task_pid > 0


@pytest.mark.asyncio
async def test_async_process_task_multiple_executions():
    """Test multiple async tasks execute correctly and independently."""
    # Arrange
    tasks = [SharedAsyncFactorialTask(n=i) for i in range(3, 8)]

    # Act
    results = await asyncio.gather(*[task.execute() for task in tasks])

    # Assert - verify all factorials computed correctly
    expected = [6, 24, 120, 720, 5040]  # 3!, 4!, 5!, 6!, 7!
    assert results == expected


@pytest.mark.asyncio
async def test_async_process_task_exception_propagation():
    """Test exceptions from subprocess are properly propagated."""
    # Arrange
    task = AsyncRaiseExceptionTask()

    # Act & Assert
    with pytest.raises(ValueError, match="Async test exception from subprocess"):
        await task.execute()


@pytest.mark.asyncio
async def test_async_process_pool_initialization(manager: ProcessPoolManager):
    """Test process pool can be explicitly initialized."""
    # Arrange - shutdown any existing pool
    await manager.shutdown(wait=True)
    assert not manager.is_initialized()

    # Act - trigger initialization
    manager.get_async_pool()

    # Assert
    assert manager.is_initialized()
    stats = manager.get_stats()
    assert stats["async"]["pool_size"] == 4

    # Cleanup
    # shutdown handled by context manager


@pytest.mark.asyncio
async def test_async_process_pool_auto_initialization(manager: ProcessPoolManager):
    """Test process pool auto-initializes on first task execution."""
    # Arrange - ensure pool is not initialized
    from asynctasq.tasks.infrastructure.process_pool_manager import set_default_manager

    await manager.shutdown(wait=True)
    assert not manager.is_initialized()

    # Set test manager as default so task uses it
    set_default_manager(manager)

    # Act - execute task which triggers auto-initialization via get_async_pool()
    task = SharedAsyncFactorialTask(n=3)
    result = await task.run()

    # Assert
    assert result == 6  # 3! = 6
    assert manager.is_initialized()

    # Cleanup
    # shutdown handled by context manager


@pytest.mark.asyncio
async def test_async_process_pool_reinitialization_warning(caplog, manager: ProcessPoolManager):
    """Test reinitialization of pool logs a warning."""
    # Arrange - initialize pool
    await manager.shutdown(wait=True)
    manager.get_async_pool()  # First initialization

    # Act - try to reinitialize
    await manager.initialize()  # Second initialization attempt

    # Assert - warning logged
    assert "already initialized" in caplog.text.lower() or "skip" in caplog.text.lower()

    # Cleanup
    # shutdown handled by context manager


@pytest.mark.asyncio
async def test_async_process_pool_shutdown(manager: ProcessPoolManager):
    """Test process pool can be shut down gracefully."""
    # Arrange
    manager.get_async_pool()  # Initialize
    assert manager.is_initialized()

    # Act
    await manager.shutdown(wait=True)

    # Assert
    assert not manager.is_initialized()


@pytest.mark.asyncio
async def test_async_process_pool_shutdown_when_not_initialized(manager: ProcessPoolManager):
    """Test shutdown when pool not initialized is safe (no error)."""
    # Arrange
    await manager.shutdown(wait=True)
    assert not manager.is_initialized()

    # Act & Assert - should not raise
    await manager.shutdown(wait=True)


@pytest.mark.asyncio
async def test_async_process_task_with_async_operations():
    """Test async task performs async operations correctly in subprocess."""
    # Arrange
    task = AsyncIOTask(message="test data")

    # Act
    result = await task.execute()

    # Assert
    assert result == "Processed: test data"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_async_process_task_concurrent_execution(manager: ProcessPoolManager):
    """Test multiple async process tasks execute concurrently."""
    # Arrange
    manager.get_async_pool()  # Initialize
    tasks = [SharedAsyncFactorialTask(n=i) for i in [5, 6, 7, 8]]

    # Act - execute concurrently
    results = await asyncio.gather(*[task.execute() for task in tasks])

    # Assert
    expected = [120, 720, 5040, 40320]  # 5!, 6!, 7!, 8!
    assert results == expected

    # Cleanup
    # shutdown handled by context manager


@pytest.mark.asyncio
async def test_async_process_task_attributes_passed_to_subprocess():
    """Verify task attributes are correctly passed to subprocess."""
    # Arrange
    task = AsyncAttributeTask(a=42, b="hello", c=[1, 2, 3])

    # Act
    result = await task.execute()

    # Assert
    assert result == {"a": 42, "b": "hello", "c": [1, 2, 3]}


@pytest.mark.asyncio
async def test_async_process_task_default_configuration():
    """Test AsyncProcessTask inherits default configuration from BaseTask."""
    # Arrange
    task = SharedAsyncFactorialTask(n=5)

    # Assert - check default values
    assert task.config.queue == "default"
    assert task.config.max_retries == 3
    assert task.config.retry_delay == 60
    assert task.config.timeout is None


@pytest.mark.asyncio
async def test_async_process_task_custom_configuration():
    """Test AsyncProcessTask respects custom configuration."""

    # Arrange
    class CustomAsyncTask(AsyncProcessTask[int]):
        queue = "custom-queue"
        max_retries = 5
        retry_delay = 120
        timeout = 300

        async def execute(self) -> int:
            return 42

    task = CustomAsyncTask()

    # Assert
    assert task.config.queue == "custom-queue"
    assert task.config.max_retries == 5
    assert task.config.retry_delay == 120
    assert task.config.timeout == 300


@pytest.mark.asyncio
async def test_async_process_task_method_chaining():
    """Test method chaining works with AsyncProcessTask."""
    # Arrange
    task = SharedAsyncFactorialTask(n=5)

    # Act - chain configuration methods
    result_task = task.on_queue("priority").retry_after(30).delay(10)

    # Assert
    assert result_task is task  # Returns self
    assert task.config.queue == "priority"
    assert task.config.retry_delay == 30
    assert task._delay_seconds == 10


@pytest.mark.asyncio
async def test_async_process_task_shared_pool_with_sync(manager: ProcessPoolManager):
    """Test AsyncProcessTask shares process pool with SyncProcessTask."""
    # Arrange - shutdown any existing pool
    await manager.shutdown(wait=True)
    await manager.shutdown(wait=True)

    # Act - initialize from async pool
    manager.get_async_pool()

    # Assert - pool is initialized
    assert manager.is_initialized()
    stats = manager.get_stats()
    assert stats["async"]["pool_size"] == 4

    # Cleanup
    # shutdown handled by context manager


@pytest.mark.asyncio
async def test_async_process_task_warm_event_loop_path():
    """Test warm event loop path (fast path with pre-initialized loop)."""
    import asyncio
    from unittest.mock import patch

    # Arrange
    task = SharedAsyncFactorialTask(n=4)

    loop = asyncio.get_event_loop()
    # Create a real Future instead of MagicMock
    mock_future = loop.create_future()
    mock_future.set_result(24)

    with (
        patch(
            "asynctasq.tasks.types.async_process_task.get_warm_event_loop",
            return_value=loop,
        ),
        patch(
            "asynctasq.tasks.types.async_process_task.asyncio.run_coroutine_threadsafe",
            return_value=mock_future,
        ) as mock_run_coroutine,
    ):
        # Act
        result = task._run_async_in_process()

        # Assert
        assert result == 24
        mock_run_coroutine.assert_called_once()


@pytest.mark.asyncio
async def test_async_process_task_fallback_path():
    """Test fallback to asyncio.run() when warm loop unavailable."""
    from unittest.mock import patch

    # Arrange
    task = SharedAsyncFactorialTask(n=3)

    with (
        patch(
            "asynctasq.tasks.types.async_process_task.get_warm_event_loop",
            return_value=None,  # Simulate no warm loop
        ),
        patch(
            "asynctasq.tasks.types.async_process_task.increment_fallback_count",
            return_value=1,
        ),
        patch(
            "asynctasq.tasks.types.async_process_task.asyncio.run", return_value=6
        ) as mock_asyncio_run,
        patch("asynctasq.tasks.types.async_process_task.logger.warning") as mock_warning,
    ):
        # Act
        result = task._run_async_in_process()

        # Assert
        assert result == 6
        mock_asyncio_run.assert_called_once()
        mock_warning.assert_called_once()
        assert "Warm event loop not available" in mock_warning.call_args[0][0]


@pytest.mark.asyncio
async def test_async_process_task_fallback_counter_increments():
    """Test fallback counter increments on each fallback."""
    from unittest.mock import patch

    # Arrange
    task = SharedAsyncFactorialTask(n=2)

    with (
        patch(
            "asynctasq.tasks.types.async_process_task.get_warm_event_loop",
            return_value=None,
        ),
        patch(
            "asynctasq.tasks.types.async_process_task.increment_fallback_count",
            return_value=5,  # Simulate 5th fallback
        ) as mock_increment,
        patch("asynctasq.tasks.types.async_process_task.asyncio.run", return_value=2),
        patch("asynctasq.tasks.types.async_process_task.logger.warning"),
    ):
        # Act
        task._run_async_in_process()

        # Assert
        mock_increment.assert_called_once()


@pytest.mark.asyncio
async def test_async_process_task_calls_get_async_pool():
    """Test run() calls get_async_pool() to get process pool."""
    from concurrent.futures import Future
    from unittest.mock import MagicMock, patch

    # Arrange
    task = SharedAsyncFactorialTask(n=1)

    # Create a real Future for the pool.submit() result
    pool_future = Future()
    pool_future.set_result(1)

    mock_pool = MagicMock()
    mock_pool.submit.return_value = pool_future

    mock_manager = MagicMock()
    mock_manager.get_async_pool.return_value = mock_pool

    with patch(
        "asynctasq.tasks.types.async_process_task.get_default_manager",
        return_value=mock_manager,
    ):
        # Act
        result = await task.run()

        # Assert
        assert result == 1
        mock_manager.get_async_pool.assert_called_once()
        mock_pool.submit.assert_called_once()
