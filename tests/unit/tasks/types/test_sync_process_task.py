"""Unit tests for SyncProcessTask class."""

import asyncio
import os

import pytest

from asynctasq.tasks import SyncProcessTask
from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

from .conftest import SharedSyncFactorialTask


class GetPIDTask(SyncProcessTask[int]):
    """Test task that returns the process ID."""

    def execute(self) -> int:
        """Return the current process ID."""
        return os.getpid()


class RaiseExceptionTask(SyncProcessTask[None]):
    """Test task that raises an exception."""

    def execute(self) -> None:
        """Raise a test exception."""
        raise ValueError("Test exception from subprocess")


class AttributeTask(SyncProcessTask[dict]):
    """Test task that verifies attribute passing to subprocess."""

    a: int
    b: str
    c: list[int]

    def execute(self) -> dict:
        """Return all attributes as dict."""
        return {"a": self.a, "b": self.b, "c": self.c}


class NotImplementedTask(SyncProcessTask[int]):
    """Test task that doesn't implement handle()."""

    pass  # Intentionally not implementing handle()


@pytest.mark.asyncio
async def test_process_task_basic_execution():
    """Test SyncProcessTask executes successfully and returns correct result."""
    # Arrange
    task = SharedSyncFactorialTask(n=5)

    # Act
    result = await task.run()

    # Assert
    assert result == 120  # 5! = 120


@pytest.mark.asyncio
async def test_process_task_isolation():
    """Verify each task runs in separate process (not main process)."""
    # Arrange
    task = GetPIDTask()
    main_pid = os.getpid()

    # Act
    task_pid = await task.run()

    # Assert - task should run in different process
    assert task_pid != main_pid
    assert isinstance(task_pid, int)
    assert task_pid > 0


@pytest.mark.asyncio
async def test_process_task_multiple_executions():
    """Test multiple tasks execute correctly and independently."""
    # Arrange
    tasks = [SharedSyncFactorialTask(n=i) for i in range(3, 8)]

    # Act
    results = await asyncio.gather(*[task.run() for task in tasks])

    # Assert - verify all factorials computed correctly
    expected = [6, 24, 120, 720, 5040]  # 3!, 4!, 5!, 6!, 7!
    assert results == expected


@pytest.mark.asyncio
async def test_process_task_exception_propagation():
    """Test exceptions in subprocess are propagated to main process."""
    # Arrange
    task = RaiseExceptionTask()

    # Act & Assert - exception should propagate
    with pytest.raises(ValueError, match="Test exception from subprocess"):
        await task.run()


@pytest.mark.asyncio
async def test_process_pool_initialization():
    """Test explicit pool initialization with custom parameters."""
    # Arrange - shutdown any existing pool
    ProcessPoolManager.shutdown_pools(wait=True)

    # Act - initialize with custom parameters
    ProcessPoolManager.initialize_sync_pool(max_workers=2, max_tasks_per_child=10)

    # Assert - pool should be initialized
    assert ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["sync"]["pool_size"] == 2
    assert stats["sync"]["max_tasks_per_child"] == 10

    # Cleanup
    ProcessPoolManager.shutdown_pools(wait=True)


@pytest.mark.asyncio
async def test_process_pool_auto_initialization():
    """Test pool is auto-initialized on first use if not explicitly initialized."""
    # Arrange - ensure pool not initialized
    ProcessPoolManager.shutdown_pools(wait=True)
    assert not ProcessPoolManager.is_initialized()

    # Act - execute task without explicit initialization
    task = SharedSyncFactorialTask(n=4)
    result = await task.run()

    # Assert - pool should be auto-initialized and task should execute
    assert ProcessPoolManager.is_initialized()
    assert result == 24  # 4! = 24

    # Cleanup
    ProcessPoolManager.shutdown_pools(wait=True)


@pytest.mark.asyncio
async def test_process_pool_reinitialization_warning(caplog):
    """Test warning logged if pool already initialized."""
    # Arrange - ensure pool is initialized
    ProcessPoolManager.shutdown_pools(wait=True)
    ProcessPoolManager.initialize_sync_pool(max_workers=2)

    # Act - try to initialize again
    ProcessPoolManager.initialize_sync_pool(max_workers=4)

    # Assert - warning should be logged, pool size unchanged
    assert "already initialized" in caplog.text
    stats = ProcessPoolManager.get_stats()
    assert stats["sync"]["pool_size"] == 2  # Original size preserved

    # Cleanup
    ProcessPoolManager.shutdown_pools(wait=True)


@pytest.mark.asyncio
async def test_process_pool_shutdown():
    """Test pool shutdown properly cleans up resources."""
    # Arrange - initialize pool
    ProcessPoolManager.initialize_sync_pool(max_workers=2)
    assert ProcessPoolManager.is_initialized()

    # Act - shutdown pool
    ProcessPoolManager.shutdown_pools(wait=True)

    # Assert - pool should be cleaned up
    assert not ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["sync"]["status"] == "not_initialized"


@pytest.mark.asyncio
async def test_process_pool_shutdown_when_not_initialized():
    """Test shutdown is safe when pool not initialized."""
    # Arrange - ensure pool not initialized
    ProcessPoolManager.shutdown_pools(wait=True)

    # Act & Assert - should not raise exception
    ProcessPoolManager.shutdown_pools(wait=True)


@pytest.mark.asyncio
async def test_process_task_with_large_computation():
    """Test SyncProcessTask handles larger computation correctly."""
    # Arrange - larger factorial
    task = SharedSyncFactorialTask(n=10)

    # Act
    result = await task.run()

    # Assert
    assert result == 3628800  # 10!


@pytest.mark.asyncio
async def test_process_task_concurrent_execution():
    """Test multiple SyncProcessTasks can execute concurrently."""
    # Arrange - create multiple tasks
    tasks = [SharedSyncFactorialTask(n=i) for i in [5, 6, 7, 8]]

    # Act - execute concurrently
    start = asyncio.get_running_loop().time()
    results = await asyncio.gather(*[task.run() for task in tasks])
    elapsed = asyncio.get_running_loop().time() - start

    # Assert - all results correct
    expected = [120, 720, 5040, 40320]
    assert results == expected

    # Performance check - concurrent execution should be faster than sequential
    # (This is a weak check - mainly verifies concurrency works)
    assert elapsed < 10.0  # Should complete in reasonable time


@pytest.mark.asyncio
async def test_process_task_attributes_passed_to_subprocess():
    """Test task attributes are correctly passed to subprocess."""
    # Arrange
    task = AttributeTask(a=1, b="test", c=[1, 2, 3])

    # Act
    result = await task.run()

    # Assert - attributes should be available in subprocess
    assert result == {"a": 1, "b": "test", "c": [1, 2, 3]}


# Cleanup fixture to ensure pool is shutdown after all tests
@pytest.fixture(scope="module", autouse=True)
def cleanup_process_pool():
    """Ensure process pool is shutdown after all tests."""
    yield
    # Cleanup after all tests in module
    ProcessPoolManager.shutdown_pools(wait=True)
