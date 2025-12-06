"""
Integration tests for RabbitMQDriver using real RabbitMQ.

These tests use a real RabbitMQ instance running in Docker for testing.

Setup:
    1. You can either setup the infrastructure of the integration tests locally or using the docker image
        A) Local
            1. Install RabbitMQ: brew install rabbitmq (macOS) or apt-get install rabbitmq-server (Linux)
            2. Start RabbitMQ: brew services start rabbitmq (macOS) or systemctl start rabbitmq-server (Linux)
        B) Docker
            1. Navigate to `tests/infrastructure` which has the docker compose file
            2. Run the container: docker compose up -d

    2. Then you can run these tests: pytest -m integration

Note:
    These are INTEGRATION tests, not unit tests. They require RabbitMQ running.
    Mark them with @mark.integration and run separately from unit tests.
"""

import asyncio
from collections.abc import AsyncGenerator
from time import time

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from pytest import fixture, main, mark
import pytest_asyncio

from asynctasq.drivers.rabbitmq_driver import RabbitMQDriver

# Test configuration
RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"
TEST_EXCHANGE = "test_asynctasq"


@fixture(scope="session")
def rabbitmq_url() -> str:
    """
    RabbitMQ connection URL.

    Override this fixture in conftest.py if using custom RabbitMQ configuration.
    """
    return RABBITMQ_URL


@pytest_asyncio.fixture
async def rabbitmq_connection(rabbitmq_url: str) -> AsyncGenerator[AbstractRobustConnection, None]:
    """
    Create a RabbitMQ connection for direct operations.
    """
    connection = await aio_pika.connect_robust(rabbitmq_url)
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def rabbitmq_driver(rabbitmq_url: str) -> AsyncGenerator[RabbitMQDriver, None]:
    """
    Create a RabbitMQDriver instance configured for testing.
    """
    driver = RabbitMQDriver(
        url=rabbitmq_url,
        exchange_name=TEST_EXCHANGE,
        prefetch_count=1,
    )

    # Connect the driver
    await driver.connect()

    yield driver

    # Cleanup: disconnect
    await driver.disconnect()


@pytest_asyncio.fixture(autouse=True)
async def clean_queues(
    rabbitmq_driver: RabbitMQDriver, rabbitmq_connection: AbstractRobustConnection
) -> AsyncGenerator[None, None]:
    """
    Fixture that ensures queues are clean before and after tests.
    Automatically applied to all tests in this module.
    """
    # Clean up any existing queues before test using driver purge_queue
    for queue_name in [
        "default",
        "test_queue",
        "queue1",
        "queue2",
        "new_queue",
        "empty_queue",
        "empty",
        "auto_created_queue",
    ]:
        try:
            await rabbitmq_driver.purge_queue(queue_name)
        except Exception:
            pass
    # Also purge queues created by many_queues test
    for i in range(50):
        try:
            await rabbitmq_driver.purge_queue(f"queue{i}")
        except Exception:
            pass

    yield

    # Clean up queues after test using driver purge_queue
    for queue_name in [
        "default",
        "test_queue",
        "queue1",
        "queue2",
        "new_queue",
        "empty_queue",
        "empty",
        "auto_created_queue",
    ]:
        try:
            await rabbitmq_driver.purge_queue(queue_name)
        except Exception:
            pass
    for i in range(50):
        try:
            await rabbitmq_driver.purge_queue(f"queue{i}")
        except Exception:
            pass


@mark.integration
class TestRabbitMQDriverWithRealRabbitMQ:
    """Integration tests for RabbitMQDriver using real RabbitMQ.

    Tests validate AMQP operations, delayed messages via TTL, message acknowledgments,
    and queue management.
    """

    @mark.asyncio
    async def test_driver_initialization(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test that driver initializes correctly with real RabbitMQ."""
        assert rabbitmq_driver.connection is not None
        assert rabbitmq_driver.channel is not None
        assert rabbitmq_driver.url == RABBITMQ_URL
        assert rabbitmq_driver.exchange_name == TEST_EXCHANGE

        # Verify connection works
        assert rabbitmq_driver.connection is not None
        assert not rabbitmq_driver.connection.is_closed

    @mark.asyncio
    async def test_enqueue_and_dequeue_single_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test enqueuing and dequeuing a single task."""
        # Arrange
        task_data = b"test_task_data"

        # Act - Enqueue
        await rabbitmq_driver.enqueue("default", task_data)

        # Act - Dequeue
        dequeued_data = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert dequeued_data == task_data

    @mark.asyncio
    async def test_enqueue_immediate_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Immediate task (delay=0) should be added to main queue."""
        # Arrange
        task_data = b"immediate_task"

        # Act
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=0)

        # Assert - task should be in main queue
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_enqueue_creates_queue_automatically(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """enqueue() should auto-create queues in RabbitMQ."""
        # Arrange
        task_data = b"new_queue_task"

        # Act
        await rabbitmq_driver.enqueue("new_queue", task_data)

        # Assert - queue should exist and be accessible
        result = await rabbitmq_driver.dequeue("new_queue", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_enqueue_multiple_tasks_preserves_fifo_order(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Tasks should be queued in FIFO order."""
        # Arrange
        tasks = [b"task1", b"task2", b"task3"]

        # Act
        for task in tasks:
            await rabbitmq_driver.enqueue("default", task)

        # Assert - dequeue in same order
        dequeued_tasks = []
        for _ in tasks:
            result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
            if result:
                dequeued_tasks.append(result)

        assert dequeued_tasks == tasks

    @mark.asyncio
    async def test_enqueue_delayed_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Delayed task should be added to delayed queue with TTL."""
        # Arrange
        task_data = b"delayed_task"
        delay_seconds = 5

        # Act
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert - task should not be immediately available
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result is None

        # Wait for delay
        await asyncio.sleep(delay_seconds + 0.5)

        # Now should be available
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_enqueue_to_different_queues(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Tasks can be enqueued to different queues independently."""
        # Arrange & Act
        await rabbitmq_driver.enqueue("queue1", b"task1")
        await rabbitmq_driver.enqueue("queue2", b"task2")

        # Assert
        task1 = await rabbitmq_driver.dequeue("queue1", poll_seconds=0)
        task2 = await rabbitmq_driver.dequeue("queue2", poll_seconds=0)
        assert task1 == b"task1"
        assert task2 == b"task2"

    @mark.asyncio
    async def test_dequeue_returns_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """dequeue() should return enqueued task."""
        # Arrange
        task_data = b"test_task"
        await rabbitmq_driver.enqueue("default", task_data)

        # Act
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result == task_data

    @mark.asyncio
    async def test_dequeue_fifo_order(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """dequeue() should return tasks in FIFO order."""
        # Arrange
        tasks = [b"first", b"second", b"third"]
        for task in tasks:
            await rabbitmq_driver.enqueue("default", task)

        # Act
        results = []
        for _ in range(3):
            result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
            if result:
                results.append(result)

        # Assert
        assert results == tasks

    @mark.asyncio
    async def test_dequeue_empty_queue_returns_none(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """dequeue() should return None for empty queue with poll_seconds=0."""
        # Act
        result = await rabbitmq_driver.dequeue("empty_queue", poll_seconds=0)

        # Assert
        assert result is None

    @mark.asyncio
    async def test_dequeue_with_poll_waits(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """dequeue() with poll_seconds should wait for tasks."""

        # Arrange
        async def enqueue_delayed():
            await asyncio.sleep(0.2)
            await rabbitmq_driver.enqueue("default", b"delayed")

        # Act
        enqueue_task = asyncio.create_task(enqueue_delayed())
        result = await rabbitmq_driver.dequeue("default", poll_seconds=1)

        # Assert
        assert result == b"delayed"

        # Cleanup
        await enqueue_task

    @mark.asyncio
    async def test_dequeue_poll_expires(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """dequeue() should return None when poll duration expires."""
        # Act
        start = time()
        result = await rabbitmq_driver.dequeue("empty", poll_seconds=1)
        elapsed = time() - start

        # Assert
        assert result is None
        assert elapsed >= 0.9  # Account for some timing variance

    @mark.asyncio
    async def test_ack_removes_from_queue(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """ack() removes task from queue."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task")
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await rabbitmq_driver.ack("default", receipt)

        # Assert - task should not be in queue
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result is None

    @mark.asyncio
    async def test_nack_requeues_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """nack() should add task back to queue for retry."""
        # Arrange
        task_data = b"failed_task"
        await rabbitmq_driver.enqueue("default", task_data)
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt == task_data

        # Act
        await rabbitmq_driver.nack("default", receipt)

        # Assert - task should be back in queue
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_nack_after_ack_is_safe(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """nack() after ack() should not requeue task."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task")
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await rabbitmq_driver.ack("default", receipt)

        # Act - nack on already-acked task
        await rabbitmq_driver.nack("default", receipt)

        # Assert - task should NOT be in queue
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result is None

    @mark.asyncio
    async def test_get_queue_size_returns_count(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """get_queue_size() should return number of tasks in main queue."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1")
        await rabbitmq_driver.enqueue("default", b"task2")
        await rabbitmq_driver.enqueue("default", b"task3")

        # Act
        size = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 3

    @mark.asyncio
    async def test_get_queue_size_empty_queue(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """get_queue_size() should return 0 for empty queue."""
        # Act
        size = await rabbitmq_driver.get_queue_size(
            "empty", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 0

    @mark.asyncio
    async def test_get_queue_size_with_delayed_flag(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """get_queue_size() behavior with include_delayed flag."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"immediate")
        await rabbitmq_driver.enqueue("default", b"delayed", delay_seconds=100)

        # Act
        size_without_delayed = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        size_with_delayed = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )

        # Assert
        assert size_without_delayed == 1  # Only immediate task counted
        assert size_with_delayed == 2  # Both immediate and delayed tasks counted

    @mark.asyncio
    async def test_delayed_task_becomes_available(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Integration: Delayed task should become available after short delay."""
        # Arrange
        task_data = b"delayed_task"
        # Set delay of 1 second
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=1)

        # Act - should not be available immediately
        result1 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result1 is None

        # Wait for delay
        await asyncio.sleep(1.2)
        result2 = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result2 == task_data

    @mark.asyncio
    async def test_ack_twice_is_safe(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Acking the same receipt handle twice should be safe."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task")
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act - ack twice
        await rabbitmq_driver.ack("default", receipt)
        await rabbitmq_driver.ack("default", receipt)  # Second ack

        # Assert - should not raise, receipt handle should be cleared
        assert receipt not in rabbitmq_driver._receipt_handles

    @mark.asyncio
    async def test_nack_then_ack_is_safe(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Acking after nack should be safe."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task")
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act - nack then ack
        await rabbitmq_driver.nack("default", receipt)
        await rabbitmq_driver.ack("default", receipt)  # Should not raise

        # Assert - receipt handle should be cleared
        assert receipt not in rabbitmq_driver._receipt_handles

    @mark.asyncio
    async def test_operations_auto_connect(self, rabbitmq_url: str) -> None:
        """Operations should auto-connect if not connected."""
        # Arrange
        driver = RabbitMQDriver(url=rabbitmq_url, exchange_name=TEST_EXCHANGE)

        try:
            # Act - operations without explicit connect
            await driver.enqueue("default", b"task")  # Should auto-connect
            assert driver.connection is not None

            result = await driver.dequeue("default", poll_seconds=0)  # Should work
            assert result == b"task"

            await driver.ack("default", result)  # Should work

            size = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )  # Should work
            assert size == 0

        finally:
            # Cleanup
            await driver.disconnect()

    @mark.asyncio
    async def test_dequeue_poll_with_task_arrival(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Polling should find tasks that arrive during poll."""

        # Arrange
        async def enqueue_after_delay():
            await asyncio.sleep(0.5)
            await rabbitmq_driver.enqueue("default", b"arrived_during_poll")

        # Act - start polling, then enqueue task
        enqueue_task = asyncio.create_task(enqueue_after_delay())
        result = await rabbitmq_driver.dequeue("default", poll_seconds=2)

        # Assert
        assert result == b"arrived_during_poll"
        await enqueue_task

    @mark.asyncio
    async def test_receipt_handle_cleanup_on_ack(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Receipt handles should be cleaned up after ack."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1")
        await rabbitmq_driver.enqueue("default", b"task2")

        receipt1 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        receipt2 = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None
        assert len(rabbitmq_driver._receipt_handles) == 2

        # Act
        await rabbitmq_driver.ack("default", receipt1)

        # Assert
        assert receipt1 not in rabbitmq_driver._receipt_handles
        assert receipt2 in rabbitmq_driver._receipt_handles
        assert len(rabbitmq_driver._receipt_handles) == 1

        # Cleanup
        await rabbitmq_driver.ack("default", receipt2)

    @mark.asyncio
    async def test_receipt_handle_cleanup_on_nack(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Receipt handles should be cleaned up after nack."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1")
        await rabbitmq_driver.enqueue("default", b"task2")

        receipt1 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        receipt2 = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None
        assert len(rabbitmq_driver._receipt_handles) == 2

        # Act
        await rabbitmq_driver.nack("default", receipt1)

        # Assert
        assert receipt1 not in rabbitmq_driver._receipt_handles
        assert receipt2 in rabbitmq_driver._receipt_handles
        assert len(rabbitmq_driver._receipt_handles) == 1

        # Cleanup
        await rabbitmq_driver.ack("default", receipt2)


@mark.integration
class TestRabbitMQDriverConcurrency:
    """Test concurrent operations with RabbitMQDriver.

    Validates async-safe operations with multiple concurrent workers.
    """

    @mark.asyncio
    async def test_concurrent_enqueue(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Multiple concurrent enqueues should all succeed."""
        # Arrange
        num_tasks = 50

        # Act
        await asyncio.gather(
            *[rabbitmq_driver.enqueue("default", f"task{i}".encode()) for i in range(num_tasks)]
        )

        # Assert
        size = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size == num_tasks

    @mark.asyncio
    async def test_concurrent_dequeue(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Multiple concurrent dequeues should get unique tasks."""
        # Arrange
        num_tasks = 30
        for i in range(num_tasks):
            await rabbitmq_driver.enqueue("default", f"task{i}".encode())

        # Act
        results = await asyncio.gather(
            *[rabbitmq_driver.dequeue("default", poll_seconds=0) for _ in range(num_tasks)]
        )

        # Assert
        results = [r for r in results if r is not None]
        assert len(results) == num_tasks
        # All tasks should be unique
        unique_results = set(results)
        assert len(unique_results) == num_tasks

    @mark.asyncio
    async def test_concurrent_enqueue_dequeue(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Concurrent enqueues and dequeues should work correctly.

        Tests that when tasks are enqueued slowly over time, concurrent consumers
        can successfully dequeue all of them using polling.
        """
        num_tasks = 20
        results = []

        async def producer():
            """Slowly enqueue tasks one at a time."""
            for i in range(num_tasks):
                await rabbitmq_driver.enqueue("default", f"task{i}".encode())
                await asyncio.sleep(0.01)  # Simulate slow production

        async def consumer():
            """Poll and consume tasks as they become available."""
            for _ in range(num_tasks):
                result = await rabbitmq_driver.dequeue("default", poll_seconds=2)
                if result:
                    results.append(result)

        # Act - run producer and consumer truly concurrently
        await asyncio.gather(producer(), consumer())

        # Assert - all tasks were successfully consumed
        assert len(results) == num_tasks
        assert len(set(results)) == num_tasks  # All unique


@mark.integration
class TestRabbitMQDriverEdgeCases:
    """Test edge cases and error conditions."""

    @mark.asyncio
    async def test_many_queues(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Driver should handle many queues efficiently."""
        # Arrange
        num_queues = 50

        # Act
        for i in range(num_queues):
            await rabbitmq_driver.enqueue(f"queue{i}", f"data{i}".encode())

        # Assert - verify all queues have tasks
        for i in range(num_queues):
            size = await rabbitmq_driver.get_queue_size(
                f"queue{i}", include_delayed=False, include_in_flight=False
            )
            assert size == 1

    @mark.asyncio
    async def test_queue_name_with_special_characters(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Queue names with special characters should work."""
        # Arrange
        queue_names = ["queue:with:colons", "queue-with-dashes", "queue_with_underscores"]

        # Act & Assert
        for queue_name in queue_names:
            await rabbitmq_driver.enqueue(queue_name, b"data")
            result = await rabbitmq_driver.dequeue(queue_name, poll_seconds=0)
            assert result == b"data"

    @mark.asyncio
    async def test_reconnect_after_disconnect(self, rabbitmq_url: str) -> None:
        """Driver should be reusable after disconnect."""
        # Arrange
        driver = RabbitMQDriver(url=rabbitmq_url, exchange_name=TEST_EXCHANGE)
        await driver.connect()

        task1 = b"task1"
        task2 = b"task2"

        try:
            # Act - use, disconnect, reconnect, use again
            await driver.enqueue("default", task1)
            result1 = await driver.dequeue("default", poll_seconds=0)
            assert result1 == task1
            await driver.ack("default", result1)

            await driver.disconnect()
            await driver.connect()

            await driver.enqueue("default", task2)
            result2 = await driver.dequeue("default", poll_seconds=0)

            # Assert
            assert result2 == task2

        finally:
            # Cleanup
            await driver.disconnect()

    @mark.asyncio
    async def test_dequeue_preserves_task_data_integrity(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
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
            await rabbitmq_driver.enqueue("default", task_data)
            result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
            assert result == task_data, f"Failed for {task_data!r}"
            if result is not None:
                await rabbitmq_driver.ack("default", result)

    @mark.asyncio
    async def test_delay_values(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test different delay value behaviors."""
        # Test zero delay
        await rabbitmq_driver.enqueue("default", b"task_zero", delay_seconds=0)
        result_zero = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result_zero == b"task_zero"
        await rabbitmq_driver.ack("default", result_zero)

        # Test negative delay (should be immediately available, goes directly to main queue)
        await rabbitmq_driver.enqueue("default", b"task_negative", delay_seconds=-1)
        result_negative = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result_negative == b"task_negative"
        await rabbitmq_driver.ack("default", result_negative)

    @mark.asyncio
    async def test_connect_is_idempotent(self, rabbitmq_url: str) -> None:
        """Multiple connect() calls should be safe."""
        # Arrange
        driver = RabbitMQDriver(url=rabbitmq_url, exchange_name=TEST_EXCHANGE)

        # Act
        await driver.connect()
        first_connection = driver.connection
        await driver.connect()  # Second call
        second_connection = driver.connection

        # Assert
        assert first_connection is second_connection

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_disconnect_is_idempotent(self, rabbitmq_url: str) -> None:
        """Multiple disconnect() calls should be safe."""
        # Arrange
        driver = RabbitMQDriver(url=rabbitmq_url, exchange_name=TEST_EXCHANGE)
        await driver.connect()

        # Act & Assert - should not raise
        await driver.disconnect()
        await driver.disconnect()  # Second call

        assert driver.connection is None

    @mark.asyncio
    async def test_get_queue_size_different_queues(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """get_queue_size should only count tasks in specified queue."""
        # Arrange
        await rabbitmq_driver.enqueue("queue1", b"task1")
        await rabbitmq_driver.enqueue("queue1", b"task2")
        await rabbitmq_driver.enqueue("queue2", b"task3")

        # Act
        size1 = await rabbitmq_driver.get_queue_size(
            "queue1", include_delayed=False, include_in_flight=False
        )
        size2 = await rabbitmq_driver.get_queue_size(
            "queue2", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size1 == 2
        assert size2 == 1


@mark.integration
@mark.parametrize("delay_seconds", [1, 2, 3])
class TestRabbitMQDriverDelayedTasks:
    """Test delayed task processing with various delays."""

    @mark.asyncio
    async def test_delayed_task_not_immediately_available(
        self, rabbitmq_driver: RabbitMQDriver, delay_seconds: int
    ) -> None:
        """Delayed tasks should not be immediately available."""
        # Arrange
        task_data = b"delayed_task"

        # Act - Enqueue with delay
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert - Should not be immediately available
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result is None

        # Wait for delay
        await asyncio.sleep(delay_seconds + 0.5)

        # Assert - Should now be available
        dequeued_data = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert dequeued_data == task_data


@mark.integration
class TestRabbitMQDriverAdditionalCoverage:
    """Additional tests to improve coverage and test edge cases."""

    @mark.asyncio
    async def test_get_queue_size_all_flag_combinations(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test all combinations of get_queue_size flags."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"immediate1")
        await rabbitmq_driver.enqueue("default", b"immediate2")
        await rabbitmq_driver.enqueue("default", b"delayed", delay_seconds=100)
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)  # Dequeue one

        # Test all 4 combinations
        size_00 = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        size_10 = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )
        size_01 = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=True
        )
        size_11 = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=True
        )

        # Assert
        assert size_00 == 1  # Only remaining immediate task
        assert size_10 == 2  # Remaining immediate + delayed
        assert size_01 == 2  # Remaining immediate + in-flight (driver counts in-flight)
        assert size_11 == 3  # Remaining immediate + delayed + in-flight

        # Cleanup
        if receipt is not None:
            await rabbitmq_driver.ack("default", receipt)

    @mark.asyncio
    async def test_multiple_delayed_tasks_different_delays(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test multiple delayed tasks with different delay values."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1", delay_seconds=1)
        await rabbitmq_driver.enqueue("default", b"task2", delay_seconds=2)
        await rabbitmq_driver.enqueue("default", b"task3", delay_seconds=3)

        # Assert - none should be immediately available
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result is None

        # Wait for first task
        await asyncio.sleep(1.2)
        result1 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result1 == b"task1"

        # Wait for second task
        await asyncio.sleep(1.0)
        result2 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result2 == b"task2"

        # Wait for third task
        await asyncio.sleep(1.0)
        result3 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result3 == b"task3"

    @mark.asyncio
    async def test_ack_without_dequeue_is_safe(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Acking a receipt handle that doesn't exist should be safe."""
        # Arrange
        fake_receipt = b"fake_receipt_handle"

        # Act & Assert - should not raise
        await rabbitmq_driver.ack("default", fake_receipt)

    @mark.asyncio
    async def test_nack_without_dequeue_is_safe(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Nacking a receipt handle that doesn't exist should be safe."""
        # Arrange
        fake_receipt = b"fake_receipt_handle"

        # Act & Assert - should not raise
        await rabbitmq_driver.nack("default", fake_receipt)

    @mark.asyncio
    async def test_dequeue_after_nack_gets_same_task(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """After nack, the same task should be available again."""
        # Arrange
        task_data = b"retry_task"
        await rabbitmq_driver.enqueue("default", task_data)
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert receipt == task_data

        # Act - nack
        await rabbitmq_driver.nack("default", receipt)

        # Assert - task should be available again
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_get_queue_size_with_delayed_queue_only(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """get_queue_size should handle delayed queue only scenario."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"delayed", delay_seconds=100)

        # Act
        size_without = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        size_with = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )

        # Assert
        assert size_without == 0  # No immediate tasks
        assert size_with == 1  # One delayed task

    @mark.asyncio
    async def test_concurrent_ack_nack_operations(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Concurrent ack and nack operations should be safe."""
        # Arrange
        num_tasks = 20
        for i in range(num_tasks):
            await rabbitmq_driver.enqueue("default", f"task{i}".encode())

        receipts = []
        for _ in range(num_tasks):
            receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)
            if receipt:
                receipts.append(receipt)

        assert len(receipts) == num_tasks

        # Act - concurrently ack and nack
        async def ack_even():
            for i, receipt in enumerate(receipts):
                if i % 2 == 0:
                    await rabbitmq_driver.ack("default", receipt)

        async def nack_odd():
            for i, receipt in enumerate(receipts):
                if i % 2 == 1:
                    await rabbitmq_driver.nack("default", receipt)

        await asyncio.gather(ack_even(), nack_odd())

        # Assert - all receipt handles should be cleared
        assert len(rabbitmq_driver._receipt_handles) == 0

    @mark.asyncio
    async def test_queue_auto_creation_on_multiple_operations(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Queues should be auto-created on various operations."""
        # Arrange
        queue_name = "auto_created_queue"

        # Act - operations should auto-create queue
        await rabbitmq_driver.enqueue(queue_name, b"task1")
        size1 = await rabbitmq_driver.get_queue_size(
            queue_name, include_delayed=False, include_in_flight=False
        )
        assert size1 == 1

        result = await rabbitmq_driver.dequeue(queue_name, poll_seconds=0)
        assert result == b"task1"

        # Queue should still exist
        size2 = await rabbitmq_driver.get_queue_size(
            queue_name, include_delayed=False, include_in_flight=False
        )
        assert size2 == 0

    @mark.asyncio
    async def test_very_short_delay(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test with very short delay (less than 1 second)."""
        # Arrange
        task_data = b"short_delay_task"
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=0)

        # Act
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        # Assert - should be immediately available
        assert result == task_data

    @mark.asyncio
    async def test_large_number_of_tasks(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test handling large number of tasks."""
        # Arrange
        num_tasks = 100

        # Act
        for i in range(num_tasks):
            await rabbitmq_driver.enqueue("default", f"task{i}".encode())

        # Assert
        size = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size == num_tasks

        # Dequeue all
        dequeued = []
        for _ in range(num_tasks):
            result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
            if result:
                dequeued.append(result)
                await rabbitmq_driver.ack("default", result)

        assert len(dequeued) == num_tasks

    @mark.asyncio
    async def test_delayed_task_with_zero_delay(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Delayed task with zero delay should behave like immediate task."""
        # Arrange
        task_data = b"zero_delay_task"

        # Act
        await rabbitmq_driver.enqueue("default", task_data, delay_seconds=0)

        # Assert - should be immediately available
        result = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        assert result == task_data

    @mark.asyncio
    async def test_get_queue_size_empty_delayed_queue(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """get_queue_size should handle empty delayed queue."""
        # Arrange - no tasks

        # Act
        size = await rabbitmq_driver.get_queue_size(
            "empty", include_delayed=True, include_in_flight=False
        )

        # Assert
        assert size == 0

    @mark.asyncio
    async def test_receipt_handle_persistence_across_operations(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Receipt handles should persist across multiple operations."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1")
        await rabbitmq_driver.enqueue("default", b"task2")

        receipt1 = await rabbitmq_driver.dequeue("default", poll_seconds=0)
        receipt2 = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None

        # Act - perform other operations
        await rabbitmq_driver.enqueue("default", b"task3")
        size = await rabbitmq_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert - receipt handles should still be valid
        assert receipt1 in rabbitmq_driver._receipt_handles
        assert receipt2 in rabbitmq_driver._receipt_handles
        assert size == 1  # task3 is in queue

        # Cleanup
        await rabbitmq_driver.ack("default", receipt1)
        await rabbitmq_driver.ack("default", receipt2)


@mark.integration
class TestRabbitMQDriverManagementMethods:
    """Test RabbitMQDriver management and stats methods."""

    @mark.asyncio
    async def test_get_queue_stats_returns_correct_stats(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_queue_stats() returns correct queue statistics."""
        # Arrange
        await rabbitmq_driver.enqueue("stats_queue", b"task1")
        await rabbitmq_driver.enqueue("stats_queue", b"task2")
        await rabbitmq_driver.enqueue("stats_queue", b"task3")

        # Act
        stats = await rabbitmq_driver.get_queue_stats("stats_queue")

        # Assert
        assert stats["name"] == "stats_queue"
        assert stats["depth"] >= 3  # At least 3 tasks
        assert stats["processing"] == 0  # No in-flight tasks
        assert stats["completed_total"] == 0  # AMQP doesn't track completed
        assert stats["failed_total"] == 0  # AMQP doesn't track failed

    @mark.asyncio
    async def test_get_queue_stats_includes_delayed_tasks(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_queue_stats() includes delayed tasks in depth."""
        # Arrange
        await rabbitmq_driver.enqueue("stats_queue", b"immediate")
        await rabbitmq_driver.enqueue("stats_queue", b"delayed", delay_seconds=100)

        # Act
        stats = await rabbitmq_driver.get_queue_stats("stats_queue")

        # Assert
        assert stats["depth"] >= 2  # Immediate + delayed

    @mark.asyncio
    async def test_get_queue_stats_includes_in_flight(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_queue_stats() includes in-flight messages in processing count."""
        # Arrange
        await rabbitmq_driver.enqueue("stats_queue", b"task1")
        await rabbitmq_driver.enqueue("stats_queue", b"task2")

        # Dequeue to create in-flight messages
        receipt1 = await rabbitmq_driver.dequeue("stats_queue", poll_seconds=0)
        receipt2 = await rabbitmq_driver.dequeue("stats_queue", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None

        # Act
        stats = await rabbitmq_driver.get_queue_stats("stats_queue")

        # Assert
        assert stats["processing"] == 2  # 2 in-flight messages

        # Cleanup
        await rabbitmq_driver.ack("stats_queue", receipt1)
        await rabbitmq_driver.ack("stats_queue", receipt2)

    @mark.asyncio
    async def test_get_all_queue_names_returns_accessed_queues(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_all_queue_names() returns queues that have been accessed."""
        # Arrange
        await rabbitmq_driver.enqueue("queue_a", b"task1")
        await rabbitmq_driver.enqueue("queue_b", b"task2")
        await rabbitmq_driver.enqueue("queue_c", b"task3")

        # Act
        queue_names = await rabbitmq_driver.get_all_queue_names()

        # Assert
        assert "queue_a" in queue_names
        assert "queue_b" in queue_names
        assert "queue_c" in queue_names

    @mark.asyncio
    async def test_get_all_queue_names_excludes_delayed_queues(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_all_queue_names() excludes delayed queue names."""
        # Arrange
        await rabbitmq_driver.enqueue("main_queue", b"delayed", delay_seconds=100)

        # Act
        queue_names = await rabbitmq_driver.get_all_queue_names()

        # Assert
        assert "main_queue" in queue_names
        assert "main_queue_delayed" not in queue_names

    @mark.asyncio
    async def test_get_global_stats_aggregates_all_queues(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_global_stats() aggregates stats from all queues."""
        # Arrange
        await rabbitmq_driver.enqueue("global_queue1", b"task1")
        await rabbitmq_driver.enqueue("global_queue1", b"task2")
        await rabbitmq_driver.enqueue("global_queue2", b"task3")

        # Act
        stats = await rabbitmq_driver.get_global_stats()

        # Assert
        assert stats["pending"] >= 3  # At least 3 tasks across queues
        assert stats["running"] >= 0
        assert stats["completed"] == 0  # AMQP doesn't track completed
        assert stats["failed"] == 0  # AMQP doesn't track failed
        assert stats["total"] >= 3

    @mark.asyncio
    async def test_get_global_stats_includes_in_flight(
        self, rabbitmq_driver: RabbitMQDriver
    ) -> None:
        """Test get_global_stats() includes in-flight messages."""
        # Arrange
        await rabbitmq_driver.enqueue("global_queue", b"task1")
        await rabbitmq_driver.enqueue("global_queue", b"task2")

        receipt1 = await rabbitmq_driver.dequeue("global_queue", poll_seconds=0)
        receipt2 = await rabbitmq_driver.dequeue("global_queue", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None

        # Act
        stats = await rabbitmq_driver.get_global_stats()

        # Assert
        assert stats["running"] >= 2  # At least 2 in-flight
        assert stats["total"] >= 2

        # Cleanup
        await rabbitmq_driver.ack("global_queue", receipt1)
        await rabbitmq_driver.ack("global_queue", receipt2)

    @mark.asyncio
    async def test_get_running_tasks_returns_empty(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test get_running_tasks() returns empty list (AMQP limitation)."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task")
        receipt = await rabbitmq_driver.dequeue("default", poll_seconds=0)

        # Act
        tasks = await rabbitmq_driver.get_running_tasks(limit=50, offset=0)

        # Assert - AMQP doesn't track task metadata
        assert tasks == []

        # Cleanup
        if receipt is not None:
            await rabbitmq_driver.ack("default", receipt)

    @mark.asyncio
    async def test_get_tasks_returns_empty(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test get_tasks() returns empty list (AMQP limitation)."""
        # Arrange
        await rabbitmq_driver.enqueue("default", b"task1")
        await rabbitmq_driver.enqueue("default", b"task2")

        # Act
        tasks, total = await rabbitmq_driver.get_tasks(
            status="pending", queue="default", limit=50, offset=0
        )

        # Assert - AMQP doesn't track task metadata
        assert tasks == []
        assert total == 0

    @mark.asyncio
    async def test_get_task_by_id_returns_none(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test get_task_by_id() returns None (AMQP limitation)."""
        # Act
        task = await rabbitmq_driver.get_task_by_id("test-task-id")

        # Assert - AMQP doesn't track task IDs
        assert task is None

    @mark.asyncio
    async def test_retry_task_returns_false(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test retry_task() returns False (AMQP limitation)."""
        # Act
        result = await rabbitmq_driver.retry_task("test-task-id")

        # Assert - AMQP doesn't track task IDs or failed tasks
        assert result is False

    @mark.asyncio
    async def test_delete_task_returns_false(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test delete_task() returns False (AMQP limitation)."""
        # Act
        result = await rabbitmq_driver.delete_task("test-task-id")

        # Assert - AMQP doesn't track task IDs
        assert result is False

    @mark.asyncio
    async def test_get_worker_stats_returns_empty(self, rabbitmq_driver: RabbitMQDriver) -> None:
        """Test get_worker_stats() returns empty list (AMQP limitation)."""
        # Act
        workers = await rabbitmq_driver.get_worker_stats()

        # Assert - AMQP doesn't track worker information
        assert workers == []


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
