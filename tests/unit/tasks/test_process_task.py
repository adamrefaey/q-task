"""Unit tests for ProcessTask class."""

import asyncio
import os

import pytest

from asynctasq.tasks import ProcessTask


class SimpleFactorialTask(ProcessTask[int]):
    """Test task that computes factorial in separate process."""

    n: int  # Type annotation for task attribute

    def handle_process(self) -> int:
        """Compute factorial of self.n."""
        n = self.n
        result = 1
        for i in range(1, n + 1):
            result *= i
        return result


class GetPIDTask(ProcessTask[int]):
    """Test task that returns the process ID."""

    def handle_process(self) -> int:
        """Return the current process ID."""
        return os.getpid()


class RaiseExceptionTask(ProcessTask[None]):
    """Test task that raises an exception."""

    def handle_process(self) -> None:
        """Raise a test exception."""
        raise ValueError("Test exception from subprocess")


class AttributeTask(ProcessTask[dict]):
    """Test task that verifies attribute passing to subprocess."""

    a: int
    b: str
    c: list[int]

    def handle_process(self) -> dict:
        """Return all attributes as dict."""
        return {"a": self.a, "b": self.b, "c": self.c}


class NotImplementedTask(ProcessTask[int]):
    """Test task that doesn't implement handle_process()."""

    pass  # Intentionally not implementing handle()


@pytest.mark.asyncio
async def test_process_task_basic_execution():
    """Test ProcessTask executes successfully and returns correct result."""
    # Arrange
    task = SimpleFactorialTask(n=5)

    # Act
    result = await task.execute()

    # Assert
    assert result == 120  # 5! = 120


@pytest.mark.asyncio
async def test_process_task_isolation():
    """Verify each task runs in separate process (not main process)."""
    # Arrange
    task = GetPIDTask()
    main_pid = os.getpid()

    # Act
    task_pid = await task.execute()

    # Assert - task should run in different process
    assert task_pid != main_pid
    assert isinstance(task_pid, int)
    assert task_pid > 0


@pytest.mark.asyncio
async def test_process_task_multiple_executions():
    """Test multiple tasks execute correctly and independently."""
    # Arrange
    tasks = [SimpleFactorialTask(n=i) for i in range(3, 8)]

    # Act
    results = await asyncio.gather(*[task.execute() for task in tasks])

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
        await task.execute()


@pytest.mark.asyncio
async def test_process_task_not_implemented():
    """Test error raised if handle_process() not overridden."""
    # Arrange & Act & Assert - Can't even instantiate abstract class
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        NotImplementedTask()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_process_pool_initialization():
    """Test explicit pool initialization with custom parameters."""
    # Arrange - shutdown any existing pool
    ProcessTask.shutdown_pool(wait=True)

    # Act - initialize with custom parameters
    ProcessTask.initialize_pool(max_workers=2, max_tasks_per_child=10)

    # Assert - pool should be initialized
    assert ProcessTask._process_pool is not None
    assert ProcessTask._pool_size == 2
    assert ProcessTask._max_tasks_per_child == 10

    # Cleanup
    ProcessTask.shutdown_pool(wait=True)


@pytest.mark.asyncio
async def test_process_pool_auto_initialization():
    """Test pool auto-initializes on first task execution if not initialized."""
    # Arrange - ensure pool is not initialized
    ProcessTask.shutdown_pool(wait=True)
    assert ProcessTask._process_pool is None

    # Act - execute task without explicit initialization
    task = SimpleFactorialTask(n=4)
    result = await task.execute()

    # Assert - pool should be auto-initialized and task should execute
    assert ProcessTask._process_pool is not None
    assert result == 24  # 4! = 24

    # Cleanup
    ProcessTask.shutdown_pool(wait=True)


@pytest.mark.asyncio
async def test_process_pool_reinitialization_warning(caplog):
    """Test warning logged if pool already initialized."""
    # Arrange - ensure pool is initialized
    ProcessTask.shutdown_pool(wait=True)
    ProcessTask.initialize_pool(max_workers=2)

    # Act - try to initialize again
    ProcessTask.initialize_pool(max_workers=4)

    # Assert - warning should be logged, pool size unchanged
    assert "already initialized" in caplog.text
    assert ProcessTask._pool_size == 2  # Original size preserved

    # Cleanup
    ProcessTask.shutdown_pool(wait=True)


@pytest.mark.asyncio
async def test_process_pool_shutdown():
    """Test pool shutdown properly cleans up resources."""
    # Arrange - initialize pool
    ProcessTask.initialize_pool(max_workers=2)
    assert ProcessTask._process_pool is not None

    # Act - shutdown pool
    ProcessTask.shutdown_pool(wait=True)

    # Assert - pool should be cleaned up
    assert ProcessTask._process_pool is None
    assert ProcessTask._pool_size is None
    assert ProcessTask._max_tasks_per_child is None


@pytest.mark.asyncio
async def test_process_pool_shutdown_when_not_initialized():
    """Test shutdown is safe when pool not initialized."""
    # Arrange - ensure pool not initialized
    ProcessTask.shutdown_pool(wait=True)

    # Act & Assert - should not raise exception
    ProcessTask.shutdown_pool(wait=True)


@pytest.mark.asyncio
async def test_process_task_with_large_computation():
    """Test ProcessTask handles larger computation correctly."""
    # Arrange - larger factorial
    task = SimpleFactorialTask(n=10)

    # Act
    result = await task.execute()

    # Assert
    assert result == 3628800  # 10!


@pytest.mark.asyncio
async def test_process_task_concurrent_execution():
    """Test multiple ProcessTasks can execute concurrently."""
    # Arrange - create multiple tasks
    tasks = [SimpleFactorialTask(n=i) for i in [5, 6, 7, 8]]

    # Act - execute concurrently
    start = asyncio.get_event_loop().time()
    results = await asyncio.gather(*[task.execute() for task in tasks])
    elapsed = asyncio.get_event_loop().time() - start

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
    result = await task.execute()

    # Assert - attributes should be available in subprocess
    assert result == {"a": 1, "b": "test", "c": [1, 2, 3]}


# Cleanup fixture to ensure pool is shutdown after all tests
@pytest.fixture(scope="module", autouse=True)
def cleanup_process_pool():
    """Ensure process pool is shutdown after all tests."""
    yield
    # Cleanup after all tests in module
    ProcessTask.shutdown_pool(wait=True)
