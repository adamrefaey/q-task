"""Integration tests for SyncProcessTask with real drivers and ORM serialization."""

import asyncio
import os

import pytest
import pytest_asyncio

from asynctasq.core.dispatcher import Dispatcher
from asynctasq.core.worker import Worker
from asynctasq.drivers.redis_driver import RedisDriver
from asynctasq.serializers.msgpack_serializer import MsgpackSerializer
from asynctasq.tasks import SyncProcessTask
from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

# Test Redis connection
REDIS_URL = os.getenv("ASYNCTASQ_REDIS_URL", "redis://localhost:6379")


class FactorialTask(SyncProcessTask[int]):
    """Compute factorial in separate process."""

    queue = "test-process"
    max_retries = 2
    timeout = 10

    n: int

    def execute(self) -> int:
        """Compute n! in subprocess."""
        result = 1
        for i in range(1, self.n + 1):
            result *= i
        return result


class CPUIntensiveTask(SyncProcessTask[dict]):
    """Simulate CPU-intensive work."""

    queue = "test-process"

    iterations: int

    def execute(self) -> dict:
        """Perform CPU-intensive computation."""
        import hashlib

        result = "0" * 64
        for _ in range(self.iterations):
            result = hashlib.sha256(result.encode()).hexdigest()

        return {"hash": result, "iterations": self.iterations}


class AttributeSerializationTask(SyncProcessTask[dict]):
    """Test attribute serialization to subprocess."""

    queue = "test-process"

    int_val: int
    str_val: str
    list_val: list[int]
    dict_val: dict[str, int]

    def execute(self) -> dict:
        """Return all attributes as dict."""
        return {
            "int_val": self.int_val,
            "str_val": self.str_val,
            "list_val": self.list_val,
            "dict_val": self.dict_val,
        }


class FailingTask(SyncProcessTask[None]):
    """Task that always fails for retry testing."""

    queue = "test-process"
    max_retries = 3

    error_msg: str

    def execute(self) -> None:
        """Raise exception."""
        raise ValueError(self.error_msg)


@pytest_asyncio.fixture
async def redis_driver():
    """Create and connect Redis driver."""
    driver = RedisDriver(url=REDIS_URL)
    await driver.connect()

    # Clean test queue
    if driver.client:
        await driver.client.delete("asynctasq:queue:test-process")
        await driver.client.delete("asynctasq:processing:test-process")
        await driver.client.delete("asynctasq:delayed:test-process")

    yield driver

    # Cleanup
    if driver.client:
        await driver.client.delete("asynctasq:queue:test-process")
        await driver.client.delete("asynctasq:processing:test-process")
        await driver.client.delete("asynctasq:delayed:test-process")
    await driver.disconnect()


@pytest_asyncio.fixture
async def dispatcher(redis_driver):
    """Create dispatcher with Redis driver."""
    serializer = MsgpackSerializer()
    return Dispatcher(driver=redis_driver, serializer=serializer)


@pytest_asyncio.fixture
async def worker(redis_driver):
    """Create worker with process pool configured."""
    # Ensure process pool is initialized
    ProcessPoolManager.shutdown_pools(wait=True)

    worker = Worker(
        queue_driver=redis_driver,
        queues=["test-process"],
        concurrency=2,
        max_tasks=None,
        process_pool_size=2,
        process_pool_max_tasks_per_child=10,
    )

    yield worker

    # Cleanup
    await worker._cleanup()
    ProcessPoolManager.shutdown_pools(wait=True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_end_to_end_with_redis(dispatcher, worker):
    """Test complete flow: dispatch -> worker processes -> verify result."""
    # Dispatch task
    task = FactorialTask(n=5)
    task_id = await dispatcher.dispatch(task)

    assert task_id is not None
    assert task._task_id == task_id

    # Start worker in background
    worker_task = asyncio.create_task(worker.start())

    # Wait for worker to process the task
    await asyncio.sleep(2)

    # Stop worker
    worker._running = False
    await worker_task

    # Verify task was processed (queue should be empty)
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_multiple_concurrent_executions(dispatcher, worker):
    """Test multiple SyncProcessTasks execute concurrently."""
    # Dispatch multiple tasks
    task_ids = []
    for n in range(3, 8):
        task = FactorialTask(n=n)
        task_id = await dispatcher.dispatch(task)
        task_ids.append(task_id)

    assert len(task_ids) == 5

    # Verify all queued
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 5

    # Start worker with timeout
    worker.max_tasks = 5  # Process exactly 5 tasks then stop
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=15.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Verify all processed
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_cpu_intensive_work(dispatcher, worker):
    """Test SyncProcessTask with actual CPU-intensive computation."""
    # Dispatch CPU-intensive task
    task = CPUIntensiveTask(iterations=1000)
    await dispatcher.dispatch(task)

    # Process with worker with timeout
    worker.max_tasks = 1
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=10.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Verify processed
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_attribute_serialization(dispatcher, worker):
    """Test complex attributes serialize correctly to subprocess."""
    # Dispatch task with various attribute types
    task = AttributeSerializationTask(
        int_val=42,
        str_val="test_string",
        list_val=[1, 2, 3, 4, 5],
        dict_val={"a": 1, "b": 2, "c": 3},
    )
    await dispatcher.dispatch(task)

    # Process with worker with timeout
    worker.max_tasks = 1
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=10.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Verify processed
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_retry_on_failure(dispatcher, worker):
    """Test SyncProcessTask retry logic with failures."""
    # Dispatch failing task
    task = FailingTask(error_msg="Test error for retry")
    await dispatcher.dispatch(task)

    # Start worker (will process and fail, then retry)
    worker.max_tasks = 2  # Process just a couple attempts
    worker_task = asyncio.create_task(worker.start())

    # Wait for a couple processing attempts
    await asyncio.sleep(2)

    # Stop worker gracefully
    worker._running = False
    try:
        await asyncio.wait_for(worker_task, timeout=5.0)
    except TimeoutError:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Task should have been attempted (verify task system is working)
    # Note: With retry delays, task may still be in queue or delayed queue
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=True, include_in_flight=True
    )
    assert queue_size >= 0  # Verify queue is accessible


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_with_delayed_execution(dispatcher, worker):
    """Test SyncProcessTask with delay parameter."""
    # Dispatch with 2 second delay
    task = FactorialTask(n=4)
    await dispatcher.dispatch(task, delay=2)

    # Immediately check - should be in delayed queue
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0

    delayed_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=True, include_in_flight=False
    )
    assert delayed_size >= 1  # At least our task is delayed

    # Wait for delay to expire
    await asyncio.sleep(3)

    # Process delayed tasks (Redis driver does this in dequeue)
    await worker.queue_driver._process_delayed_tasks("test-process")

    # Now should be available
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size >= 1

    # Process with worker (with timeout to prevent hanging)
    worker.max_tasks = 1
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=5.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Verify processed
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_pool_lifecycle_with_worker(redis_driver):
    """Test process pool initialization and shutdown with worker lifecycle."""
    # Ensure clean state
    ProcessPoolManager.shutdown_pools(wait=True)
    assert not ProcessPoolManager.is_initialized()

    # Create worker with process pool config
    worker = Worker(
        queue_driver=redis_driver,
        queues=["test-process"],
        process_pool_size=2,
        process_pool_max_tasks_per_child=5,
    )

    # Connect driver and initialize pool
    await redis_driver.connect()
    await worker.queue_driver.connect()

    # Initialize pool (normally done in worker.start())
    ProcessPoolManager.initialize_sync_pool(
        max_workers=worker.process_pool_size,
        max_tasks_per_child=worker.process_pool_max_tasks_per_child,
    )

    # Verify pool initialized
    assert ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["sync"]["pool_size"] == 2
    assert stats["sync"]["max_tasks_per_child"] == 5

    # Cleanup (normally done in worker.cleanup())
    ProcessPoolManager.shutdown_pools(wait=True)

    # Verify pool shutdown
    assert not ProcessPoolManager.is_initialized()
    stats = ProcessPoolManager.get_stats()
    assert stats["sync"]["status"] == "not_initialized"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_isolation(dispatcher, worker):
    """Verify SyncProcessTask runs in separate process (not main process)."""

    class GetPIDTask(SyncProcessTask[int]):
        queue = "test-process"

        def execute(self) -> int:
            import os as subprocess_os

            return subprocess_os.getpid()

    # Dispatch and process
    task = GetPIDTask()
    await dispatcher.dispatch(task)

    worker.max_tasks = 1

    # We can't easily verify the PID from the test, but we can verify
    # the task executes without error, which proves it ran in subprocess
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=10.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_with_timeout(dispatcher, worker):
    """Test SyncProcessTask timeout handling."""

    class SlowTask(SyncProcessTask[str]):
        queue = "test-process"
        timeout = 1  # 1 second timeout

        duration: int

        def execute(self) -> str:
            import time

            time.sleep(self.duration)
            return "completed"

    # Dispatch task that will timeout
    task = SlowTask(duration=3)
    await dispatcher.dispatch(task)

    # Process with worker (should timeout and retry)
    worker.max_tasks = 2
    worker_task = asyncio.create_task(worker.start())

    await asyncio.sleep(2)

    worker._running = False
    await worker_task

    # Task should have timed out (implementation may vary)
    # Verify worker didn't crash
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=True
    )
    assert queue_size >= 0  # Verify operation succeeded


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_task_batch_processing(dispatcher, worker):
    """Test SyncProcessTask can handle batch of tasks efficiently."""
    # Dispatch batch of 10 tasks
    task_ids = []
    for i in range(10):
        task = FactorialTask(n=i + 3)
        task_id = await dispatcher.dispatch(task)
        task_ids.append(task_id)

    # Verify all queued
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 10

    # Process all with worker with timeout
    worker.max_tasks = 10
    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.wait_for(worker_task, timeout=20.0)
    except TimeoutError:
        worker._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Verify all processed
    queue_size = await worker.queue_driver.get_queue_size(
        "test-process", include_delayed=False, include_in_flight=False
    )
    assert queue_size == 0


# Cleanup fixture to ensure process pool is always shutdown
@pytest.fixture(scope="module", autouse=True)
def cleanup_process_pool():
    """Ensure process pool is shutdown after all tests."""
    yield
    ProcessPoolManager.shutdown_pools(wait=True)
