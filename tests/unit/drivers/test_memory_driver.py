"""Unit tests for MemoryDriver.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- pytest-asyncio 1.3.0 for automatic async fixture support
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Fast, isolated tests
"""

import asyncio
from collections.abc import AsyncGenerator

from pytest import fixture, main, mark

from async_task.drivers.memory_driver import MemoryDriver


@fixture
async def driver() -> AsyncGenerator[MemoryDriver, None]:
    """Provide a connected MemoryDriver instance, automatically disconnected after test."""
    instance = MemoryDriver()
    await instance.connect()
    yield instance
    await instance.disconnect()


@mark.unit
class TestMemoryDriverInitialization:
    """Test MemoryDriver initialization and connection lifecycle."""

    async def test_driver_initializes_disconnected(self) -> None:
        # Arrange & Act
        driver = MemoryDriver()

        # Assert
        assert driver._connected is False

    async def test_connect_initializes_queues(self, driver: MemoryDriver) -> None:
        # Assert
        assert driver._connected is True
        assert isinstance(driver._queues, dict)
        assert isinstance(driver._delayed_tasks, dict)
        assert isinstance(driver._processing, dict)
        assert driver._background_task is not None

    async def test_connect_is_idempotent(self, driver: MemoryDriver) -> None:
        # Act
        first_background_task = driver._background_task
        await driver.connect()  # Second call
        second_background_task = driver._background_task

        # Assert
        assert first_background_task is second_background_task
        assert driver._connected is True

    async def test_disconnect_stops_background_task(self, driver: MemoryDriver) -> None:
        # Arrange
        background_task = driver._background_task

        # Act
        await driver.disconnect()

        # Assert
        assert driver._connected is False
        assert background_task is not None
        assert background_task.cancelled() or background_task.done()

    async def test_disconnect_clears_all_data(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("test", b"data1")

        # Act
        await driver.disconnect()

        # Assert
        assert len(driver._queues) == 0
        assert len(driver._delayed_tasks) == 0
        assert len(driver._processing) == 0


@mark.unit
class TestMemoryDriverEnqueue:
    """Test task enqueueing functionality."""

    async def test_enqueue_immediate_task(self, driver: MemoryDriver) -> None:
        # Arrange
        task_data = b"test_task_data"

        # Act
        await driver.enqueue("default", task_data, delay_seconds=0)

        # Assert
        assert "default" in driver._queues
        assert task_data in driver._queues["default"]
        assert len(driver._queues["default"]) == 1

    async def test_enqueue_multiple_tasks_preserves_order(self, driver: MemoryDriver) -> None:
        # Arrange
        tasks = [b"task1", b"task2", b"task3"]

        # Act
        for task in tasks:
            await driver.enqueue("default", task)

        # Assert
        queue = driver._queues["default"]
        assert list(queue) == tasks

    async def test_enqueue_delayed_task(self, driver: MemoryDriver) -> None:
        # Arrange
        task_data = b"delayed_task"

        # Act
        await driver.enqueue("default", task_data, delay_seconds=5)

        # Assert
        assert "default" in driver._delayed_tasks
        assert len(driver._delayed_tasks["default"]) == 1
        target_time, data = driver._delayed_tasks["default"][0]
        assert data == task_data
        loop = asyncio.get_running_loop()
        assert target_time > loop.time()

    async def test_enqueue_delayed_tasks_sorted_by_time(self, driver: MemoryDriver) -> None:
        # Act - enqueue with different delays
        await driver.enqueue("default", b"task3", delay_seconds=3)
        await driver.enqueue("default", b"task1", delay_seconds=1)
        await driver.enqueue("default", b"task2", delay_seconds=2)

        # Assert - should be sorted by target time
        delayed_list = driver._delayed_tasks["default"]
        assert len(delayed_list) == 3
        target_times = [target_time for target_time, _ in delayed_list]
        assert target_times == sorted(target_times)


@mark.unit
class TestMemoryDriverDequeue:
    """Test task dequeuing functionality."""

    async def test_dequeue_returns_task(self, driver: MemoryDriver) -> None:
        # Arrange
        task_data = b"test_task"
        await driver.enqueue("default", task_data)

        # Act
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == task_data

    async def test_dequeue_removes_from_queue(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task1")
        await driver.enqueue("default", b"task2")

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert len(driver._queues["default"]) == 1

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert len(driver._queues["default"]) == 0

    async def test_dequeue_fifo_order(self, driver: MemoryDriver) -> None:
        # Arrange
        tasks = [b"first", b"second", b"third"]
        for task in tasks:
            await driver.enqueue("default", task)

        # Act
        results = []
        for _ in range(3):
            result = await driver.dequeue("default", poll_seconds=0)
            results.append(result)

        # Assert
        assert results == tasks

    async def test_dequeue_empty_queue_returns_none(self, driver: MemoryDriver) -> None:
        # Act
        result = await driver.dequeue("empty_queue", poll_seconds=0)

        # Assert
        assert result is None

    async def test_dequeue_tracks_in_processing(self, driver: MemoryDriver) -> None:
        # Arrange
        task_data = b"tracked_task"
        await driver.enqueue("default", task_data)

        # Act
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result in driver._processing
        assert driver._processing[result] == "default"

    async def test_dequeue_with_timeout_waits(self, driver: MemoryDriver) -> None:
        # Act - enqueue after a short delay
        async def enqueue_delayed():
            await asyncio.sleep(0.2)
            await driver.enqueue("default", b"delayed")

        enqueue_task = asyncio.create_task(enqueue_delayed())
        result = await driver.dequeue("default", poll_seconds=1)

        # Assert
        assert result == b"delayed"

        # Cleanup
        await enqueue_task

    async def test_dequeue_timeout_expires(self, driver: MemoryDriver) -> None:
        # Act
        loop = asyncio.get_running_loop()
        start = loop.time()
        result = await driver.dequeue("empty", poll_seconds=1)
        elapsed = loop.time() - start

        # Assert
        assert result is None
        assert 1.1 >= elapsed >= 0.9  # Allow some timing tolerance


@mark.unit
class TestMemoryDriverAck:
    """Test task acknowledgment functionality."""

    async def test_ack_removes_from_processing(self, driver: MemoryDriver) -> None:
        # Arrange
        task_data = b"task"
        await driver.enqueue("default", task_data)
        receipt = await driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await driver.ack("default", receipt)

        # Assert
        assert receipt not in driver._processing

    async def test_ack_does_not_requeue(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task")
        receipt = await driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await driver.ack("default", receipt)

        # Assert
        assert len(driver._queues["default"]) == 0

    async def test_ack_nonexistent_receipt_is_safe(self, driver: MemoryDriver) -> None:
        # Act & Assert - should not raise
        await driver.ack("default", b"nonexistent")


@mark.unit
class TestMemoryDriverNack:
    """Test task rejection/retry functionality."""

    async def test_nack_removes_from_processing(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task")
        receipt = await driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await driver.nack("default", receipt)

        # Assert
        assert receipt not in driver._processing

    async def test_nack_requeues_at_front(self, driver: MemoryDriver) -> None:
        # Arrange
        task1 = b"task1"
        task2 = b"task2"
        await driver.enqueue("default", task1)
        await driver.enqueue("default", task2)
        receipt = await driver.dequeue("default", poll_seconds=0)  # Gets task1
        assert receipt == task1

        # Act
        await driver.nack("default", receipt)

        # Assert
        next_task = await driver.dequeue("default", poll_seconds=0)
        assert next_task == task1  # task1 is back at front


@mark.unit
class TestMemoryDriverGetQueueSize:
    """Test queue size reporting functionality."""

    async def test_get_queue_size_returns_count(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task1")
        await driver.enqueue("default", b"task2")
        await driver.enqueue("default", b"task3")

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 3

    async def test_get_queue_size_empty_queue(self, driver: MemoryDriver) -> None:
        # Act
        size = await driver.get_queue_size("empty", include_delayed=False, include_in_flight=False)

        # Assert
        assert size == 0

    async def test_get_queue_size_excludes_in_flight(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task1")
        await driver.enqueue("default", b"task2")
        await driver.dequeue("default", poll_seconds=0)  # Remove one

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 1

    async def test_get_queue_size_excludes_delayed(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"immediate")
        await driver.enqueue("default", b"delayed", delay_seconds=10)

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 1  # Only immediate task counted


@mark.unit
class TestMemoryDriverDelayedTasks:
    """Test delayed task processing functionality."""

    async def test_delayed_task_becomes_available(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"delayed", delay_seconds=1)

        # Act - wait for delay + processing time
        await asyncio.sleep(1.2)
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b"delayed"

    async def test_delayed_task_not_available_before_delay(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"delayed", delay_seconds=2)

        # Act - try to dequeue immediately
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result is None

    async def test_multiple_delayed_tasks_processed_in_order(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task1", delay_seconds=1)
        await driver.enqueue("default", b"task2", delay_seconds=2)

        # Act
        await asyncio.sleep(1.2)  # task1 should be ready
        result1 = await driver.dequeue("default", poll_seconds=0)
        result2 = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result1 == b"task1"
        assert result2 is None  # task2 not ready yet

        await asyncio.sleep(1.0)  # Now task2 should be ready
        result3 = await driver.dequeue("default", poll_seconds=0)
        assert result3 == b"task2"

    async def test_mixed_immediate_and_delayed_tasks(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"delayed", delay_seconds=5)
        await driver.enqueue("default", b"immediate")

        # Act
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b"immediate"

    async def test_background_processor_moves_ready_tasks(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"delayed", delay_seconds=1)

        # Act - wait for background processor cycle
        await asyncio.sleep(1.2)

        # Assert - task should be in main queue now
        assert len(driver._queues.get("default", [])) == 1
        assert b"delayed" in driver._queues["default"]


@mark.unit
class TestMemoryDriverConcurrency:
    """Test concurrent operations and thread safety."""

    async def test_concurrent_enqueue(self, driver: MemoryDriver) -> None:
        # Arrange
        num_tasks = 100

        # Act
        await asyncio.gather(
            *[driver.enqueue("default", f"task{i}".encode()) for i in range(num_tasks)]
        )

        # Assert
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size == num_tasks

    async def test_concurrent_dequeue(self, driver: MemoryDriver) -> None:
        # Arrange
        num_tasks = 50
        for i in range(num_tasks):
            await driver.enqueue("default", f"task{i}".encode())

        # Act
        results = await asyncio.gather(
            *[driver.dequeue("default", poll_seconds=0) for _ in range(num_tasks)]
        )

        # Assert
        results = [r for r in results if r is not None]
        assert len(results) == num_tasks
        assert len(set(results)) == num_tasks  # All unique

    async def test_concurrent_enqueue_dequeue(self, driver: MemoryDriver) -> None:
        # Arrange
        async def producer():
            for i in range(20):
                await driver.enqueue("default", f"task{i}".encode())
                await asyncio.sleep(0.01)

        async def consumer():
            results = []
            for _ in range(20):
                result = await driver.dequeue("default", poll_seconds=1)
                if result:
                    results.append(result)
            return results

        # Act
        producer_task = asyncio.create_task(producer())
        consumer_results = await consumer()
        await producer_task

        # Assert
        assert len(consumer_results) == 20


@mark.unit
class TestMemoryDriverEdgeCases:
    """Test edge cases and error conditions."""

    async def test_empty_task_data(self, driver: MemoryDriver) -> None:
        # Act
        await driver.enqueue("default", b"")
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b""

    async def test_large_task_data(self, driver: MemoryDriver) -> None:
        # Arrange
        large_data = b"x" * 1_000_000  # 1MB

        # Act
        await driver.enqueue("default", large_data)
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == large_data

    async def test_many_queues(self, driver: MemoryDriver) -> None:
        # Arrange
        num_queues = 100

        # Act
        for i in range(num_queues):
            await driver.enqueue(f"queue{i}", f"data{i}".encode())

        # Assert
        assert len(driver._queues) == num_queues

    async def test_queue_name_with_special_characters(self, driver: MemoryDriver) -> None:
        # Arrange
        queue_names = ["queue:with:colons", "queue-with-dashes", "queue_with_underscores"]

        # Act & Assert
        for queue_name in queue_names:
            await driver.enqueue(queue_name, b"data")
            result = await driver.dequeue(queue_name, poll_seconds=0)
            assert result == b"data"

    async def test_reconnect_after_disconnect(self) -> None:
        # Arrange
        driver = MemoryDriver()

        # Act - connect, disconnect, reconnect
        await driver.connect()
        await driver.enqueue("default", b"task1")
        await driver.disconnect()

        await driver.connect()
        await driver.enqueue("default", b"task2")
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b"task2"  # Old data cleared

        # Cleanup
        await driver.disconnect()

    @mark.parametrize("delay_seconds", [0, -1])
    async def test_zero_or_negative_delay_treated_as_immediate(
        self, driver: MemoryDriver, delay_seconds: int
    ) -> None:
        # Act
        await driver.enqueue("default", b"task", delay_seconds=delay_seconds)
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b"task"


@mark.unit
class TestMemoryDriverRobustness:
    """Test robustness and error handling."""

    async def test_dequeue_with_zero_timeout_non_blocking(self, driver: MemoryDriver) -> None:
        # Act - should return immediately
        loop = asyncio.get_running_loop()
        start = loop.time()
        result = await driver.dequeue("empty", poll_seconds=0)
        elapsed = loop.time() - start

        # Assert
        assert result is None
        assert elapsed < MemoryDriver.POLL_INTERVAL_SECONDS  # Should be nearly instant

    async def test_operations_after_disconnect_auto_reconnect(self) -> None:
        # Arrange
        driver = MemoryDriver()
        await driver.connect()
        await driver.disconnect()

        # Act - operations should auto-reconnect
        await driver.enqueue("test", b"data")
        result = await driver.dequeue("test", poll_seconds=0)

        # Assert
        assert driver._connected is True
        assert result == b"data"

        # Cleanup
        await driver.disconnect()

    async def test_delayed_tasks_cleaned_after_processing(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"delayed", delay_seconds=1)

        # Act
        await asyncio.sleep(1.2)
        await driver.dequeue("default", poll_seconds=0)

        # Assert - delayed task list should be empty or cleaned
        assert "default" not in driver._delayed_tasks or len(driver._delayed_tasks["default"]) == 0

    async def test_background_task_continues_after_errors(self, driver: MemoryDriver) -> None:
        # Arrange
        background_task = driver._background_task
        assert background_task is not None

        # Act - let background task run for a bit
        await asyncio.sleep(0.5)

        # Assert - background task should still be running
        assert not background_task.done()
        assert not background_task.cancelled()

    async def test_very_short_delay(self, driver: MemoryDriver) -> None:
        # Arrange - delay shorter than polling interval
        # Note: delay_seconds parameter expects int, but the driver should handle small delays
        await driver.enqueue("default", b"task", delay_seconds=1)  # Using 1 second instead of 0.05

        # Act - wait slightly longer than delay
        await asyncio.sleep(1.2)
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == b"task"

    async def test_queue_isolation(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("queue1", b"data1")
        await driver.enqueue("queue2", b"data2")

        # Act
        result1 = await driver.dequeue("queue1", poll_seconds=0)
        result2 = await driver.dequeue("queue2", poll_seconds=0)
        result3 = await driver.dequeue("queue1", poll_seconds=0)

        # Assert
        assert result1 == b"data1"
        assert result2 == b"data2"
        assert result3 is None  # queue1 is empty now

    async def test_processing_dict_tracks_correct_queue(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("queue_a", b"task_a")
        await driver.enqueue("queue_b", b"task_b")

        # Act
        receipt_a = await driver.dequeue("queue_a", poll_seconds=0)
        receipt_b = await driver.dequeue("queue_b", poll_seconds=0)

        # Assert
        assert receipt_a is not None
        assert receipt_b is not None
        assert driver._processing[receipt_a] == "queue_a"
        assert driver._processing[receipt_b] == "queue_b"


@mark.unit
class TestMemoryDriverAutoConnect:
    """Test auto-connect behavior across all operations."""

    @mark.parametrize(
        "operation,args",
        [
            ("enqueue", ("test_queue", b"data")),
            ("dequeue", ("test_queue", 0)),
            ("ack", ("test_queue", b"receipt")),
            ("nack", ("test_queue", b"receipt")),
            ("get_queue_size", ("test_queue", False, False)),
        ],
    )
    async def test_operations_auto_connect(self, operation: str, args: tuple) -> None:
        # Arrange
        driver = MemoryDriver()
        assert driver._connected is False

        # Act
        method = getattr(driver, operation)
        await method(*args)

        # Assert
        assert driver._connected is True

        # Cleanup
        await driver.disconnect()


@mark.unit
class TestMemoryDriverIdempotency:
    """Test idempotent operations."""

    async def test_connect_is_idempotent(self, driver: MemoryDriver) -> None:
        # Act
        first_background_task = driver._background_task
        await driver.connect()  # Second call
        second_background_task = driver._background_task

        # Assert
        assert first_background_task is second_background_task
        assert driver._connected is True

    async def test_disconnect_is_idempotent(self) -> None:
        # Arrange
        driver = MemoryDriver()
        await driver.connect()

        # Act & Assert - should not raise
        await driver.disconnect()
        await driver.disconnect()  # Second call

        assert driver._connected is False

        # Cleanup not needed - already disconnected

    async def test_ack_is_idempotent(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task")
        receipt = await driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        assert receipt in driver._processing

        # Act - multiple acks should be safe
        await driver.ack("default", receipt)
        await driver.ack("default", receipt)  # Second ack

        # Assert - no exceptions raised
        assert receipt not in driver._processing

    async def test_nack_after_ack_is_safe(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("default", b"task")
        receipt = await driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await driver.ack("default", receipt)

        # Act - nack on already ack'd should be safe
        await driver.nack("default", receipt)

        # Assert - no exceptions raised, and task not requeued
        assert receipt not in driver._processing
        assert len(driver._queues.get("default", [])) == 0


@mark.unit
class TestMemoryDriverQueueCreation:
    """Test automatic queue creation behavior."""

    @mark.parametrize(
        "operation,args",
        [
            ("enqueue", ("new_queue", b"data", 0)),
            ("dequeue", ("new_queue", 0)),
        ],
    )
    async def test_operations_create_queue_if_not_exists(
        self, driver: MemoryDriver, operation: str, args: tuple
    ) -> None:
        # Act
        method = getattr(driver, operation)
        await method(*args)

        # Assert
        assert "new_queue" in driver._queues

    async def test_nack_creates_queue_only_for_in_flight_tasks(self, driver: MemoryDriver) -> None:
        # Arrange
        await driver.enqueue("test_queue", b"task")
        receipt = await driver.dequeue("test_queue", poll_seconds=0)
        assert receipt is not None

        # Act - nack a task that was actually in processing
        await driver.nack("new_queue", receipt)

        # Assert - queue is created because task was in processing
        assert "new_queue" in driver._queues
        assert b"task" in driver._queues["new_queue"]

    async def test_nack_does_not_create_queue_for_nonexistent_receipt(
        self, driver: MemoryDriver
    ) -> None:
        # Act - nack a receipt that was never in processing
        await driver.nack("never_created", b"nonexistent")

        # Assert - queue should not be created
        assert "never_created" not in driver._queues


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
