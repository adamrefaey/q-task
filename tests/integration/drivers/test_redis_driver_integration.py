"""
Integration tests for RedisDriver using real Redis.

These tests use a real Redis instance running in Docker for testing.

Setup:
    1. You can either setup the infrastructure of the integration tests locally or using the docker image
        A) Local
            1. Install Redis: brew install redis (macOS) or apt-get install redis (Linux)
            2. Start Redis: redis-server
        B) Docker
            1. Navigate to `tests/infrastructure` which has the docker compose file
            2. Run the container: docker compose up -d

    2. Then you can run these tests: pytest -m integration

Note:
    These are INTEGRATION tests, not unit tests. They require Redis running.
    Mark them with @mark.integration and run separately from unit tests.
"""

import asyncio
from collections.abc import AsyncGenerator
from time import time

from pytest import fixture, main, mark
import pytest_asyncio
from redis.asyncio import Redis

from asynctasq.drivers.redis_driver import RedisDriver, maybe_await

# Test configuration
REDIS_URL = "redis://localhost:6379"
TEST_DB = 1  # Use DB 1 for tests to avoid conflicts with dev data


@fixture(scope="session")
def redis_url() -> str:
    """
    Redis connection URL.

    Override this fixture in conftest.py if using custom Redis configuration.
    """
    return REDIS_URL


@pytest_asyncio.fixture
async def redis_client(redis_url: str) -> AsyncGenerator[Redis, None]:
    """
    Create a Redis client for direct Redis operations.
    """
    client = Redis.from_url(redis_url, db=TEST_DB, decode_responses=False)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def redis_driver(redis_url: str) -> AsyncGenerator[RedisDriver, None]:
    """
    Create a RedisDriver instance configured for testing.
    """
    driver = RedisDriver(
        url=redis_url,
        db=TEST_DB,
        max_connections=10,
    )

    # Connect the driver
    await driver.connect()

    yield driver

    # Cleanup: disconnect
    await driver.disconnect()


@pytest_asyncio.fixture(autouse=True)
async def clean_queue(redis_client: Redis) -> AsyncGenerator[None, None]:
    """
    Fixture that ensures Redis is clean before and after tests.
    Automatically applied to all tests in this module.
    """
    # Clear DB before test
    await redis_client.flushdb()

    yield

    # Clear DB after test
    await redis_client.flushdb()


@mark.integration
class TestRedisDriverWithRealRedis:
    """Integration tests for RedisDriver using real Redis.

    Tests validate the Reliable Queue Pattern implementation using LMOVE/BLMOVE
    as documented in https://redis.io/docs/latest/commands/lmove/
    """

    @mark.asyncio
    async def test_driver_initialization(self, redis_driver: RedisDriver) -> None:
        """Test that driver initializes correctly with real Redis."""
        assert redis_driver.client is not None
        assert redis_driver.url == REDIS_URL
        assert redis_driver.db == TEST_DB

        # Verify connection works
        assert await maybe_await(redis_driver.client.ping())

    @mark.asyncio
    async def test_enqueue_and_dequeue_single_task(self, redis_driver: RedisDriver) -> None:
        """Test enqueuing and dequeuing a single task."""
        # Arrange
        task_data = b"test_task_data"

        # Act - Enqueue
        await redis_driver.enqueue("default", task_data)

        # Act - Dequeue
        dequeued_data = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert dequeued_data == task_data

    @mark.asyncio
    async def test_enqueue_immediate_task(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Immediate task (delay=0) should be added to Redis list."""
        # Arrange
        task_data = b"immediate_task"

        # Act
        await redis_driver.enqueue("default", task_data, delay_seconds=0)

        # Assert
        result = await maybe_await(redis_client.rpop("queue:default"))
        assert result == task_data

    @mark.asyncio
    async def test_enqueue_creates_queue_automatically(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """enqueue() should auto-create queues in Redis."""
        # Arrange
        task_data = b"new_queue_task"

        # Act
        await redis_driver.enqueue("new_queue", task_data)

        # Assert
        assert await maybe_await(redis_client.exists("queue:new_queue"))

    @mark.asyncio
    async def test_enqueue_multiple_tasks_preserves_fifo_order(
        self, redis_driver: RedisDriver
    ) -> None:
        """Tasks should be queued in FIFO order (LPUSH/RPOP)."""
        # Arrange
        tasks = [b"task1", b"task2", b"task3"]

        # Act
        for task in tasks:
            await redis_driver.enqueue("default", task)

        # Assert - dequeue in same order
        dequeued_tasks = []
        for _ in tasks:
            result = await redis_driver.dequeue("default", poll_seconds=0)
            if result:
                dequeued_tasks.append(result)

        assert dequeued_tasks == tasks

    @mark.asyncio
    async def test_enqueue_delayed_task(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Delayed task should be added to Redis sorted set with timestamp score."""
        # Arrange
        task_data = b"delayed_task"
        delay_seconds = 5
        before_time = time()

        # Act
        await redis_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert
        # Check task exists in delayed set
        score = await maybe_await(redis_client.zscore("queue:default:delayed", task_data))
        assert score is not None

        # Score should be approximately current_time + delay
        expected_time = before_time + delay_seconds
        assert abs(score - expected_time) < 1.0  # Within 1 second tolerance

    @mark.asyncio
    async def test_enqueue_delayed_tasks_sorted_by_time(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Delayed tasks should be sorted by execution time in Redis sorted set."""
        # Arrange
        tasks = [
            (b"task1", 10),
            (b"task2", 5),
            (b"task3", 15),
        ]

        # Act
        for task_data, delay in tasks:
            await redis_driver.enqueue("default", task_data, delay_seconds=delay)

        # Assert - tasks should be ordered by score (execution time)
        all_tasks = await maybe_await(redis_client.zrange("queue:default:delayed", 0, -1))
        assert all_tasks == [b"task2", b"task1", b"task3"]  # Sorted by delay

    @mark.asyncio
    async def test_enqueue_to_different_queues(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Tasks can be enqueued to different queues independently."""
        # Arrange & Act
        await redis_driver.enqueue("queue1", b"task1")
        await redis_driver.enqueue("queue2", b"task2")

        # Assert
        task1 = await maybe_await(redis_client.rpop("queue:queue1"))
        task2 = await maybe_await(redis_client.rpop("queue:queue2"))
        assert task1 == b"task1"
        assert task2 == b"task2"

    @mark.asyncio
    async def test_dequeue_returns_task(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """dequeue() should return enqueued task."""
        # Arrange
        task_data = b"test_task"
        await maybe_await(redis_client.lpush("queue:default", task_data))

        # Act
        result = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == task_data

    @mark.asyncio
    async def test_dequeue_moves_task_to_processing(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """dequeue() should atomically move task from main queue to processing list (LMOVE)."""
        # Arrange
        await maybe_await(redis_client.lpush("queue:default", b"task1", b"task2"))

        # Act
        dequeued = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert - task moved from main queue to processing list
        assert dequeued == b"task1"  # FIFO: LMOVE RIGHT takes from right (oldest)
        main_queue_size = await maybe_await(redis_client.llen("queue:default"))
        processing_size = await maybe_await(redis_client.llen("queue:default:processing"))
        assert main_queue_size == 1  # One task remains in main queue
        assert processing_size == 1  # One task now in processing

    @mark.asyncio
    async def test_dequeue_fifo_order(self, redis_driver: RedisDriver) -> None:
        """dequeue() should return tasks in FIFO order."""
        # Arrange
        tasks = [b"first", b"second", b"third"]
        for task in tasks:
            await redis_driver.enqueue("default", task)

        # Act
        results = []
        for _ in range(3):
            result = await redis_driver.dequeue("default", poll_seconds=0)
            if result:
                results.append(result)

        # Assert
        assert results == tasks

    @mark.asyncio
    async def test_dequeue_empty_queue_returns_none(self, redis_driver: RedisDriver) -> None:
        """dequeue() should return None for empty queue with poll_seconds=0."""
        # Act
        result = await redis_driver.dequeue("empty_queue", poll_seconds=0)

        # Assert
        assert result is None

    @mark.asyncio
    async def test_dequeue_with_poll_waits(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """dequeue() with poll_seconds should wait for tasks."""

        # Arrange
        async def enqueue_delayed():
            await asyncio.sleep(0.2)
            await maybe_await(redis_client.lpush("queue:default", b"delayed"))

        # Act
        enqueue_task = asyncio.create_task(enqueue_delayed())
        result = await redis_driver.dequeue("default", poll_seconds=1)

        # Assert
        assert result == b"delayed"

        # Cleanup
        await enqueue_task

    @mark.asyncio
    async def test_dequeue_poll_expires(self, redis_driver: RedisDriver) -> None:
        """dequeue() should return None when poll duration expires."""
        # Act
        start = time()
        result = await redis_driver.dequeue("empty", poll_seconds=1)
        elapsed = time() - start

        # Assert
        assert result is None
        assert elapsed >= 0.9  # Account for some timing variance

    @mark.asyncio
    async def test_dequeue_processes_delayed_tasks_first(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """dequeue() should move ready delayed tasks to main queue."""
        # Arrange
        task_data = b"delayed_task"
        # Add to delayed set with score in the past (ready to process)
        past_time = time() - 10
        await maybe_await(redis_client.zadd("queue:default:delayed", {task_data: past_time}))

        # Act
        result = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == task_data

        # Task should be removed from delayed set
        delayed_count = await maybe_await(redis_client.zcard("queue:default:delayed"))
        assert delayed_count == 0

    @mark.asyncio
    async def test_dequeue_skips_not_ready_delayed_tasks(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """dequeue() should not return delayed tasks that aren't ready yet."""
        # Arrange
        task_data = b"future_task"

        # Add to delayed set with score in the future
        future_time = time() + 100
        await maybe_await(redis_client.zadd("queue:default:delayed", {task_data: future_time}))

        # Act
        result = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result is None

        # Task should remain in delayed set
        delayed_count = await maybe_await(redis_client.zcard("queue:default:delayed"))
        assert delayed_count == 1

    @mark.asyncio
    async def test_ack_removes_from_processing(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """ack() removes task from processing list."""
        # Arrange
        await redis_driver.enqueue("default", b"task")
        receipt = await redis_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await redis_driver.ack("default", receipt)

        # Assert - task should not be in processing list
        processing_count = await maybe_await(redis_client.llen("queue:default:processing"))
        assert processing_count == 0

    @mark.asyncio
    async def test_nack_requeues_task(self, redis_driver: RedisDriver, redis_client: Redis) -> None:
        """nack() should add task back to queue for retry."""
        # Arrange
        task_data = b"failed_task"
        await redis_driver.enqueue("default", task_data)
        receipt = await redis_driver.dequeue("default", poll_seconds=0)
        assert receipt == task_data

        # Act
        await redis_driver.nack("default", receipt)

        # Assert - task should be back in main queue
        result = await maybe_await(redis_client.rpop("queue:default"))
        assert result == task_data

    @mark.asyncio
    async def test_nack_adds_to_front_of_queue(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """nack() should use LPUSH to add task to front for priority retry."""
        # Arrange
        # Add task1 and task2, dequeue task1
        await redis_driver.enqueue("default", b"task1")
        await redis_driver.enqueue("default", b"task2")
        task_data = await redis_driver.dequeue("default", poll_seconds=0)
        assert task_data == b"task1"

        # Act - nack adds to front with LPUSH
        await redis_driver.nack("default", task_data)

        # Assert - nacked task should come out first (before task2)
        all_tasks = await maybe_await(redis_client.lrange("queue:default", 0, -1))
        assert all_tasks[0] == task_data
        assert all_tasks[1] == b"task2"

    @mark.asyncio
    async def test_nack_after_ack_is_safe(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """nack() after ack() should not requeue task."""
        # Arrange
        await redis_driver.enqueue("default", b"task")
        receipt = await redis_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await redis_driver.ack("default", receipt)

        # Act - nack on already-acked task
        await redis_driver.nack("default", receipt)

        # Assert - task should NOT be in queue or processing list
        queue_count = await maybe_await(redis_client.llen("queue:default"))
        processing_count = await maybe_await(redis_client.llen("queue:default:processing"))
        assert queue_count == 0
        assert processing_count == 0

    @mark.asyncio
    async def test_get_queue_size_returns_count(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """get_queue_size() should return number of tasks in main queue."""
        # Arrange
        await maybe_await(redis_client.lpush("queue:default", b"task1", b"task2", b"task3"))

        # Act
        size = await redis_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 3

    @mark.asyncio
    async def test_get_queue_size_empty_queue(self, redis_driver: RedisDriver) -> None:
        """get_queue_size() should return 0 for empty queue."""
        # Act
        size = await redis_driver.get_queue_size(
            "empty", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 0

    @mark.asyncio
    async def test_get_queue_size_includes_in_flight(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """get_queue_size() should include in-flight tasks when requested."""
        # Arrange
        await redis_driver.enqueue("default", b"task1")
        await redis_driver.enqueue("default", b"task2")
        await redis_driver.dequeue("default", poll_seconds=0)  # Move task1 to processing

        # Act - without in_flight
        size_without = await redis_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        # Act - with in_flight
        size_with = await redis_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=True
        )

        # Assert
        assert size_without == 1  # Only task2 in main queue
        assert size_with == 2  # task2 in main queue + task1 in processing

    @mark.asyncio
    async def test_get_queue_size_with_delayed_flag(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """get_queue_size() behavior with include_delayed flag - validates sorted set counting."""
        # Arrange
        await maybe_await(redis_client.lpush("queue:default", b"immediate"))
        await maybe_await(redis_client.zadd("queue:default:delayed", {b"delayed": time() + 100}))

        # Act
        size_without_delayed = await redis_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        size_with_delayed = await redis_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )

        # Assert
        assert size_without_delayed == 1  # Only immediate task counted
        assert size_with_delayed == 2  # Both immediate and delayed tasks counted

    @mark.asyncio
    async def test_delayed_task_becomes_available(self, redis_driver: RedisDriver) -> None:
        """Integration: Delayed task should become available after short delay."""
        # Arrange
        task_data = b"delayed_task"
        # Set delay of 1 second
        await redis_driver.enqueue("default", task_data, delay_seconds=1)

        # Act - wait for delay
        await asyncio.sleep(1.2)
        result = await redis_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == task_data

    @mark.asyncio
    async def test_get_queue_stats_and_inspection_methods(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Integration: test get_queue_stats, get_all_queue_names, get_global_stats."""
        # Arrange - prepare a queue with pending, processing and stats
        await maybe_await(redis_client.lpush("queue:statsq", b"a", b"b"))
        await maybe_await(redis_client.lpush("queue:statsq:processing", b"p1"))
        await maybe_await(redis_client.set("queue:statsq:stats:completed", 7))
        await maybe_await(redis_client.set("queue:statsq:stats:failed", 1))

        # Act - get queue stats
        stats = await redis_driver.get_queue_stats("statsq")

        # Assert
        assert stats["name"] == "statsq"
        assert stats["depth"] == 2
        assert stats["processing"] == 1
        assert stats["completed_total"] == 7
        assert stats["failed_total"] == 1

        # Create another queue and verify get_all_queue_names + global aggregation
        await maybe_await(redis_client.lpush("queue:alpha", b"x"))
        await maybe_await(redis_client.lpush("queue:beta", b"y", b"z"))
        await maybe_await(redis_client.lpush("queue:beta:processing", b"r"))
        await maybe_await(redis_client.set("queue:alpha:stats:completed", 2))
        await maybe_await(redis_client.set("queue:beta:stats:failed", 3))

        names = await redis_driver.get_all_queue_names()
        assert {"statsq", "alpha", "beta"}.issubset(set(names))

        totals = await redis_driver.get_global_stats()
        # pending: statsq(2) + alpha(1) + beta(2) = 5
        assert totals["pending"] == 5
        # running: statsq(1) + beta(1) = 2
        assert totals["running"] == 2
        assert totals["completed"] >= 2
        assert totals["failed"] >= 3

    @mark.asyncio
    async def test_task_listing_and_lookup_and_retry_delete(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Integration: test get_running_tasks, get_tasks.

        Note: get_task_by_id, retry_task, and delete_task return None/False
        for Redis driver because they require deserialization to find task IDs.
        These operations should be done through TaskService instead.
        """
        import msgpack

        # Arrange - create pending and processing items with msgpack-serialized data
        id36 = "i" * 36
        task_pending = {"task_id": id36, "task_name": "pending_task"}
        task_processing = {"task_id": id36, "task_name": "processing_task"}
        raw_pending: bytes = msgpack.packb(task_pending)  # type: ignore[assignment]
        raw_processing: bytes = msgpack.packb(task_processing)  # type: ignore[assignment]
        await maybe_await(redis_client.lpush("queue:q", raw_pending))
        await maybe_await(redis_client.lpush("queue:q:processing", raw_processing))

        # Act - running tasks
        running = await redis_driver.get_running_tasks(limit=10)

        # Assert - now returns list of (bytes, queue_name) tuples
        assert any(r[1] == "q" for r in running)

        # get_tasks should return both pending and running
        tasks, total = await redis_driver.get_tasks()
        assert total >= 2

        # get_task_by_id returns None for Redis driver (requires deserialization)
        found = await redis_driver.get_task_by_id(id36)
        assert found is None  # Expected: Redis driver can't do ID lookup without serializer

        # retry_task returns False for Redis driver (requires deserialization)
        tid = "retry-1"
        raw_dead = (tid + ":x").encode()
        await maybe_await(redis_client.lpush("queue:q:dead", raw_dead))
        ok = await redis_driver.retry_task(tid)
        assert ok is False  # Expected: Redis driver can't do ID-based retry

        # delete_task returns False for Redis driver (requires deserialization)
        tid2 = "del-1"
        raw1 = (tid2 + ":a").encode()
        await maybe_await(redis_client.lpush("queue:q", raw1))
        removed = await redis_driver.delete_task(tid2)
        assert removed is False  # Expected: Redis driver can't do ID-based delete

        # Test raw operations work (these are the primitives TaskService uses)
        await redis_driver.delete_raw_task("q", raw1)
        pending_items = await maybe_await(redis_client.lrange("queue:q", 0, -1))
        assert raw1 not in pending_items

    @mark.asyncio
    async def test_get_worker_stats_integration(
        self, redis_driver: RedisDriver, redis_client: Redis
    ) -> None:
        """Integration: test get_worker_stats reads worker hashes."""
        # Arrange - create a worker hash
        await maybe_await(
            redis_client.hset(
                "worker:abc",
                mapping={
                    "status": "busy",
                    "tasks_processed": "4",
                    "uptime_seconds": "123",
                    "last_heartbeat": str(time()),
                },
            )
        )

        # Act
        workers = await redis_driver.get_worker_stats()

        # Assert - find worker abc
        assert any(w["worker_id"] == "abc" for w in workers)


@mark.integration
class TestRedisDriverConcurrency:
    """Test concurrent operations with RedisDriver.

    Validates thread-safe/async-safe operations using atomic Redis commands.
    """

    @mark.asyncio
    async def test_concurrent_enqueue(self, redis_driver: RedisDriver) -> None:
        """Multiple concurrent enqueues should all succeed."""
        # Arrange
        num_tasks = 50

        # Act
        await asyncio.gather(
            *[redis_driver.enqueue("default", f"task{i}".encode()) for i in range(num_tasks)]
        )

        # Assert
        size = await redis_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size == num_tasks

    @mark.asyncio
    async def test_concurrent_dequeue(self, redis_driver: RedisDriver, redis_client: Redis) -> None:
        """Multiple concurrent dequeues should get unique tasks."""
        # Arrange
        num_tasks = 30
        tasks = [f"task{i}".encode() for i in range(num_tasks)]
        for task in reversed(tasks):  # LPUSH in reverse for FIFO
            await maybe_await(redis_client.lpush("queue:default", task))

        # Act
        results = await asyncio.gather(
            *[redis_driver.dequeue("default", poll_seconds=0) for _ in range(num_tasks)]
        )

        # Assert
        results = [r for r in results if r is not None]
        results.sort()
        tasks.sort()
        assert tasks == results

    @mark.asyncio
    async def test_concurrent_enqueue_dequeue(self, redis_driver: RedisDriver) -> None:
        """Concurrent enqueues and dequeues should work correctly.

        Tests that when tasks are enqueued slowly over time, concurrent consumers
        can successfully dequeue all of them using polling.
        """
        num_tasks = 20
        results = []

        async def producer():
            """Slowly enqueue tasks one at a time."""
            for i in range(num_tasks):
                await redis_driver.enqueue("default", f"task{i}".encode())
                await asyncio.sleep(0.01)  # Simulate slow production

        async def consumer():
            """Poll and consume tasks as they become available."""
            for _ in range(num_tasks):
                result = await redis_driver.dequeue("default", poll_seconds=2)
                if result:
                    results.append(result)

        # Act - run producer and consumer truly concurrently
        await asyncio.gather(producer(), consumer())

        # Assert - all tasks were successfully consumed
        assert len(results) == num_tasks
        assert len(set(results)) == num_tasks  # All unique


@mark.integration
class TestRedisDriverEdgeCases:
    """Test edge cases and error conditions."""

    @mark.asyncio
    async def test_many_queues(self, redis_driver: RedisDriver, redis_client: Redis) -> None:
        """Driver should handle many queues efficiently."""
        # Arrange
        num_queues = 50

        # Act
        for i in range(num_queues):
            await redis_driver.enqueue(f"queue{i}", f"data{i}".encode())

        # Assert - verify all queues exist
        for i in range(num_queues):
            exists = await maybe_await(redis_client.exists(f"queue:queue{i}"))
            assert exists == 1

    @mark.asyncio
    async def test_queue_name_with_special_characters(self, redis_driver: RedisDriver) -> None:
        """Queue names with special characters should work."""
        # Arrange
        queue_names = ["queue:with:colons", "queue-with-dashes", "queue_with_underscores"]

        # Act & Assert
        for queue_name in queue_names:
            await redis_driver.enqueue(queue_name, b"data")
            result = await redis_driver.dequeue(queue_name, poll_seconds=0)
            assert result == b"data"

    @mark.asyncio
    async def test_reconnect_after_disconnect(self, redis_url: str) -> None:
        """Driver should be reusable after disconnect."""
        # Arrange
        driver = RedisDriver(url=redis_url, db=TEST_DB)
        await driver.connect()

        task1 = b"task1"
        task2 = b"task2"

        # Act - use, disconnect, reconnect, use again
        await driver.enqueue("default", task1)
        result1 = await driver.dequeue("default", poll_seconds=0)
        assert result1 == task1

        await driver.disconnect()
        await driver.connect()

        await driver.enqueue("default", task2)
        result2 = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result2 == task2

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_dequeue_preserves_task_data_integrity(self, redis_driver: RedisDriver) -> None:
        """Task data should be exactly preserved through enqueue/dequeue cycle.

        Tests binary safety, null bytes, UTF-8, and large payloads.
        """
        # Arrange
        test_cases = [
            b"",  # Empty
            b"simple",
            b"x" * 1_000_000,  # Large (1MB)
            b"with spaces",
            b"with\nnewlines\r\n",
            b"with\ttabs",
            b"\x00\x01\x02\xff",  # Binary data
            b"data\x00with\x00nulls",  # Null bytes
            b"unicode: \xc3\xa9\xc3\xa0",  # UTF-8 encoded
        ]

        # Act & Assert
        for task_data in test_cases:
            await redis_driver.enqueue("default", task_data)
            result = await redis_driver.dequeue("default", poll_seconds=0)
            assert result == task_data, f"Failed for {task_data!r}"

    @mark.asyncio
    async def test_delay_values(self, redis_driver: RedisDriver) -> None:
        """Test different delay value behaviors."""
        # Test zero delay
        await redis_driver.enqueue("default", b"task_zero", delay_seconds=0)
        result_zero = await redis_driver.dequeue("default", poll_seconds=0)
        assert result_zero == b"task_zero"

        # Test negative delay (should be immediately available, goes directly to main queue)
        await redis_driver.enqueue("default", b"task_negative", delay_seconds=-1)
        result_negative = await redis_driver.dequeue("default", poll_seconds=0)
        assert result_negative == b"task_negative"

    @mark.asyncio
    async def test_connect_is_idempotent(self, redis_url: str) -> None:
        """Multiple connect() calls should be safe."""
        # Arrange
        driver = RedisDriver(url=redis_url, db=TEST_DB)

        # Act
        await driver.connect()
        first_client = driver.client
        await driver.connect()  # Second call
        second_client = driver.client

        # Assert
        assert first_client is second_client

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_disconnect_is_idempotent(self, redis_url: str) -> None:
        """Multiple disconnect() calls should be safe."""
        # Arrange
        driver = RedisDriver(url=redis_url, db=TEST_DB)
        await driver.connect()

        # Act & Assert - should not raise
        await driver.disconnect()
        await driver.disconnect()  # Second call

        assert driver.client is None


@mark.integration
@mark.parametrize("delay_seconds", [1, 2, 3])
class TestRedisDriverDelayedTasks:
    """Test delayed task processing with various delays."""

    @mark.asyncio
    async def test_delayed_task_not_immediately_available(
        self, redis_driver: RedisDriver, delay_seconds: int
    ) -> None:
        """Delayed tasks should not be immediately available."""
        # Arrange
        task_data = b"delayed_task"

        # Act - Enqueue with delay
        await redis_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert - Should not be immediately available
        result = await redis_driver.dequeue("default", poll_seconds=0)
        assert result is None

        # Wait for delay
        await asyncio.sleep(delay_seconds + 0.5)

        # Assert - Should now be available
        dequeued_data = await redis_driver.dequeue("default", poll_seconds=0)
        assert dequeued_data == task_data


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
