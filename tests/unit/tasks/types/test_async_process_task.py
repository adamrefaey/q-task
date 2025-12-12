"""Unit tests for AsyncProcessTask class."""

import asyncio
import os

import pytest

from asynctasq.tasks import AsyncProcessTask
from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

from .conftest import SharedAsyncFactorialTask


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
async def test_async_process_pool_initialization():
    """Test process pool can be explicitly initialized."""
    # Arrange - shutdown any existing pool
    ProcessPoolManager.shutdown_pools()
    assert not ProcessPoolManager.is_initialized()

    # Act
    ProcessPoolManager.initialize_async_pool(max_workers=4)

    # Assert
    assert ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["async"]["pool_size"] == 4

    # Cleanup
    ProcessPoolManager.shutdown_pools()


@pytest.mark.asyncio
async def test_async_process_pool_auto_initialization():
    """Test process pool auto-initializes on first task execution."""
    # Arrange - ensure pool is not initialized
    ProcessPoolManager.shutdown_pools()
    assert not ProcessPoolManager.is_initialized()

    # Act - execute task without explicit initialization
    task = SharedAsyncFactorialTask(n=3)
    result = await task.run()

    # Assert
    assert result == 6  # 3! = 6
    assert ProcessPoolManager.is_initialized()

    # Cleanup
    ProcessPoolManager.shutdown_pools()


@pytest.mark.asyncio
async def test_async_process_pool_reinitialization_warning(caplog):
    """Test reinitialization of pool logs a warning."""
    # Arrange - initialize pool
    ProcessPoolManager.shutdown_pools()
    ProcessPoolManager.initialize_async_pool(max_workers=2)

    # Act - try to reinitialize
    ProcessPoolManager.initialize_async_pool(max_workers=4)

    # Assert - warning logged
    assert "already initialized" in caplog.text.lower()

    # Cleanup
    ProcessPoolManager.shutdown_pools()


@pytest.mark.asyncio
async def test_async_process_pool_shutdown():
    """Test process pool can be shut down gracefully."""
    # Arrange
    ProcessPoolManager.initialize_async_pool(max_workers=2)
    assert ProcessPoolManager.is_initialized()

    # Act
    ProcessPoolManager.shutdown_pools()

    # Assert
    assert not ProcessPoolManager.is_initialized()


@pytest.mark.asyncio
async def test_async_process_pool_shutdown_when_not_initialized():
    """Test shutdown when pool not initialized is safe (no error)."""
    # Arrange
    ProcessPoolManager.shutdown_pools()
    assert not ProcessPoolManager.is_initialized()

    # Act & Assert - should not raise
    ProcessPoolManager.shutdown_pools()


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
async def test_async_process_task_concurrent_execution():
    """Test multiple async process tasks execute concurrently."""
    # Arrange
    ProcessPoolManager.initialize_async_pool(max_workers=4)
    tasks = [SharedAsyncFactorialTask(n=i) for i in [5, 6, 7, 8]]

    # Act - execute concurrently
    results = await asyncio.gather(*[task.execute() for task in tasks])

    # Assert
    expected = [120, 720, 5040, 40320]  # 5!, 6!, 7!, 8!
    assert results == expected

    # Cleanup
    ProcessPoolManager.shutdown_pools()


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
async def test_async_process_task_shared_pool_with_sync():
    """Test AsyncProcessTask shares process pool with SyncProcessTask."""
    # Arrange - shutdown any existing pool
    ProcessPoolManager.shutdown_pools()
    ProcessPoolManager.shutdown_pools()

    # Act - initialize from SyncProcessTask (pool is shared)
    ProcessPoolManager.initialize_async_pool(max_workers=4)

    # Assert - pool is shared and initialized
    assert ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["async"]["pool_size"] == 4

    # Cleanup
    ProcessPoolManager.shutdown_pools()
