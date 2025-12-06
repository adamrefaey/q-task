"""
Integration tests for SQSDriver using LocalStack.

These tests use LocalStack to provide a real SQS instance for testing.
LocalStack is the recommended approach for testing aioboto3 code since
moto does not support aiobotocore/aioboto3.

Setup:
    1. You can either setup the infrastructure of the integration tests locally or using the docker image
        A) Local
            1. Install LocalStack: uv tool install localstack
            2. Run the scripts under `tests/infrastructure/localstack-init/ready.d/`
            3. Start LocalStack: localstack start
        B) Docker
            1. Navigate to `tests/infrastructure` which has the docker compose file
            2. Run the container: docker compose up -d

    2. Then you can run these tests: pytest -m integration

Note:
    These are INTEGRATION tests, not unit tests. They require LocalStack running.
    Mark them with @mark.integration and run separately from unit tests.
"""

import asyncio
from collections.abc import AsyncGenerator
import json
from typing import Any, cast

import aioboto3
from pytest import fixture, main, mark, raises
import pytest_asyncio

from asynctasq.drivers.sqs_driver import SQSDriver

# Test configuration
TEST_REGION = "us-east-1"
LOCALSTACK_ENDPOINT = "http://localhost:4566"
TEST_QUEUE_NAME = "test-queue"  # Use the queue created by LocalStack init script


@fixture(scope="session")
def localstack_endpoint() -> str:
    """
    LocalStack endpoint URL.

    Override this fixture in conftest.py if using custom LocalStack configuration.
    """
    return LOCALSTACK_ENDPOINT


@fixture(scope="session")
def aws_region() -> str:
    """AWS region for tests."""
    return TEST_REGION


@pytest_asyncio.fixture
async def sqs_client(localstack_endpoint: str, aws_region: str) -> AsyncGenerator:
    """
    Create an aioboto3 SQS client for LocalStack.

    Note: LocalStack doesn't require real AWS credentials.
    """
    session = aioboto3.Session()
    client_cm = cast(
        Any,
        session.client(
            "sqs",
            endpoint_url=localstack_endpoint,
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ),
    )
    async with client_cm as client:
        yield client


@pytest_asyncio.fixture
async def sqs_driver(aws_region: str) -> AsyncGenerator[SQSDriver, None]:
    """
    Create an SQSDriver instance configured for LocalStack.
    """
    driver = SQSDriver(
        region_name=aws_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url=LOCALSTACK_ENDPOINT,  # Point to LocalStack
        queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",  # LocalStack queue URL format
    )

    # Connect the driver
    await driver.connect()

    yield driver

    # Cleanup: disconnect
    await driver.disconnect()


@pytest_asyncio.fixture(autouse=True)
async def clean_queue(sqs_client, sqs_driver: SQSDriver) -> AsyncGenerator[None, None]:
    """
    Fixture that ensures the queue is empty before and after tests.
    Automatically applied to all tests in this module.
    Queue already exists from LocalStack init script.
    """
    # Purge queue before test
    try:
        queue_url = f"{LOCALSTACK_ENDPOINT}/000000000000/{TEST_QUEUE_NAME}"
        await sqs_client.purge_queue(QueueUrl=queue_url)
        await asyncio.sleep(0.5)  # Wait for purge to complete
    except Exception:
        pass  # Queue might be empty

    yield

    # Purge queue after test
    try:
        queue_url = f"{LOCALSTACK_ENDPOINT}/000000000000/{TEST_QUEUE_NAME}"
        await sqs_client.purge_queue(QueueUrl=queue_url)
    except Exception:
        pass


@mark.integration
class TestSQSDriverWithLocalStack:
    """Integration tests for SQSDriver using LocalStack."""

    @mark.asyncio
    async def test_driver_initialization(self, sqs_driver: SQSDriver) -> None:
        """Test that driver initializes correctly with LocalStack."""
        assert sqs_driver.client is not None
        assert sqs_driver.region_name == TEST_REGION

    @mark.asyncio
    async def test_enqueue_and_dequeue_single_message(self, sqs_driver: SQSDriver) -> None:
        """Test enqueuing and dequeuing a single message."""
        # Arrange
        payload = {"task": "test_task", "data": "test_data"}
        task_data = json.dumps(payload).encode("utf-8")

        # Act - Enqueue
        await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Act - Dequeue
        dequeued_data = await sqs_driver.dequeue(TEST_QUEUE_NAME)

        # Assert
        assert dequeued_data is not None
        dequeued_payload = json.loads(dequeued_data.decode("utf-8"))
        assert dequeued_payload == payload

    @mark.asyncio
    async def test_enqueue_multiple_messages(self, sqs_driver: SQSDriver) -> None:
        """Test enqueuing multiple messages."""
        # Arrange
        payloads = [
            {"task": "task_1", "data": "data_1"},
            {"task": "task_2", "data": "data_2"},
            {"task": "task_3", "data": "data_3"},
        ]

        # Act - Enqueue all
        for payload in payloads:
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Assert - Dequeue all messages
        dequeued = []
        for _ in range(len(payloads)):
            data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
            if data:
                payload = json.loads(data.decode("utf-8"))
                dequeued.append(payload)

        assert len(dequeued) == len(payloads)
        # SQS doesn't guarantee order, so check set equality
        assert {json.dumps(p, sort_keys=True) for p in dequeued} == {
            json.dumps(p, sort_keys=True) for p in payloads
        }

    @mark.asyncio
    async def test_dequeue_empty_queue(self, sqs_driver: SQSDriver) -> None:
        """Test dequeuing from an empty queue returns None."""
        # Act
        message = await sqs_driver.dequeue(TEST_QUEUE_NAME)

        # Assert
        assert message is None

    @mark.asyncio
    async def test_acknowledge_message(self, sqs_driver: SQSDriver) -> None:
        """Test acknowledging a message removes it from the queue."""
        # Arrange
        task_data = json.dumps({"task": "test_task"}).encode("utf-8")
        await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Act - Dequeue and acknowledge
        dequeued_data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued_data is not None
        await sqs_driver.ack(TEST_QUEUE_NAME, dequeued_data)

        # Assert - Message should not be dequeued again
        await asyncio.sleep(0.2)
        message2 = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert message2 is None

    @mark.asyncio
    async def test_nack_message(self, sqs_driver: SQSDriver) -> None:
        """Test negative acknowledging a message makes it visible again."""
        # Arrange
        task_data = json.dumps({"task": "test_task"}).encode("utf-8")
        await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Act - Dequeue and nack
        dequeued_data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued_data is not None
        await sqs_driver.nack(TEST_QUEUE_NAME, dequeued_data)

        # Assert - Message should be available again
        await asyncio.sleep(0.3)
        dequeued_data2 = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued_data2 is not None

    @mark.asyncio
    async def test_queue_size(self, sqs_driver: SQSDriver) -> None:
        """Test getting the queue size."""
        # Arrange - Enqueue some messages
        for i in range(3):
            payload = {"task": f"task_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Small delay to allow messages to be registered
        await asyncio.sleep(0.3)

        # Act
        size = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, False, False)

        # Assert
        assert size >= 3  # May be more if other tests are running

    @mark.asyncio
    async def test_queue_size_with_delayed(self, sqs_driver: SQSDriver) -> None:
        """Test getting queue size including delayed messages."""
        # Arrange - Enqueue messages with delay
        for i in range(2):
            payload = {"task": f"delayed_task_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data, delay_seconds=5)

        # Also enqueue immediate messages
        for i in range(2):
            payload = {"task": f"immediate_task_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        await asyncio.sleep(0.3)

        # Act - Get size including delayed
        size_with_delayed = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, True, False)
        size_without_delayed = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, False, False)

        # Assert
        assert size_with_delayed >= 4
        assert size_without_delayed >= 2
        assert size_with_delayed >= size_without_delayed

    @mark.asyncio
    async def test_queue_size_with_in_flight(self, sqs_driver: SQSDriver) -> None:
        """Test getting queue size including in-flight messages."""
        # Arrange - Enqueue messages
        for i in range(3):
            payload = {"task": f"task_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        await asyncio.sleep(0.3)

        # Act - Dequeue but don't ack (messages become in-flight)
        dequeued = []
        for _ in range(2):
            data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
            if data:
                dequeued.append(data)

        await asyncio.sleep(0.3)

        # Get size including in-flight
        size_with_in_flight = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, False, True)
        size_without_in_flight = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, False, False)

        # Assert
        assert size_with_in_flight >= 3  # Should include in-flight messages
        assert size_without_in_flight >= 1  # Only visible messages
        assert size_with_in_flight >= size_without_in_flight

        # Cleanup - ack the dequeued messages
        for data in dequeued:
            await sqs_driver.ack(TEST_QUEUE_NAME, data)

    @mark.asyncio
    async def test_queue_size_with_all_options(self, sqs_driver: SQSDriver) -> None:
        """Test getting queue size with both delayed and in-flight included."""
        # Arrange - Enqueue immediate and delayed messages
        for i in range(2):
            payload = {"task": f"immediate_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        for i in range(2):
            payload = {"task": f"delayed_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data, delay_seconds=5)

        await asyncio.sleep(0.3)

        # Dequeue one (becomes in-flight)
        dequeued = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued is not None

        await asyncio.sleep(0.3)

        # Act - Get size with all options
        size_all = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, True, True)

        # Assert
        assert size_all >= 4  # Should include all: visible + delayed + in-flight

        # Cleanup
        await sqs_driver.ack(TEST_QUEUE_NAME, dequeued)

    @mark.asyncio
    async def test_enqueue_delay_exceeds_limit(self, sqs_driver: SQSDriver) -> None:
        """Test that enqueue raises ValueError when delay_seconds > 900."""
        # Arrange
        task_data = json.dumps({"task": "test"}).encode("utf-8")

        # Act & Assert
        with raises(ValueError, match="delay_seconds cannot exceed 900"):
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data, delay_seconds=901)

        with raises(ValueError, match="delay_seconds cannot exceed 900"):
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data, delay_seconds=1000)

    @mark.asyncio
    async def test_enqueue_auto_connect(self, aws_region: str) -> None:
        """Test that enqueue auto-connects if client is None."""
        # Arrange - Create driver but don't connect
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )

        # Act - Enqueue without explicit connect
        task_data = json.dumps({"task": "auto_connect_test"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Assert - Client should be connected now
        assert driver.client is not None

        # Verify message was enqueued
        result = await driver.dequeue(TEST_QUEUE_NAME)
        assert result == task_data

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_dequeue_auto_connect(self, aws_region: str) -> None:
        """Test that dequeue auto-connects if client is None."""
        # Arrange - Create driver, connect, enqueue, then disconnect
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        task_data = json.dumps({"task": "auto_connect_dequeue"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)
        await driver.disconnect()

        # Act - Dequeue without explicit connect
        result = await driver.dequeue(TEST_QUEUE_NAME)

        # Assert - Client should be connected and message retrieved
        assert driver.client is not None
        assert result == task_data

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_ack_auto_connect(self, aws_region: str) -> None:
        """Test that ack auto-connects if client is None."""
        # Arrange - Create driver, connect, enqueue, dequeue, then disconnect
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        task_data = json.dumps({"task": "auto_connect_ack"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)
        dequeued = await driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued is not None
        await driver.disconnect()

        # Act - Ack without explicit connect
        await driver.ack(TEST_QUEUE_NAME, dequeued)

        # Assert - Client should be connected
        assert driver.client is not None

        # Verify message was acked (shouldn't be available again)
        await asyncio.sleep(0.2)
        result = await driver.dequeue(TEST_QUEUE_NAME)
        assert result is None

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_nack_auto_connect(self, aws_region: str) -> None:
        """Test that nack auto-connects if client is None."""
        # Arrange - Create driver, connect, enqueue, dequeue
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        task_data = json.dumps({"task": "auto_connect_nack"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)
        dequeued = await driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued is not None
        # Simulate client being None (but keep receipt handle in cache)
        # This tests the auto-connect path in nack
        original_client = driver.client
        driver.client = None

        # Act - Nack without explicit connect (should auto-connect)
        await driver.nack(TEST_QUEUE_NAME, dequeued)

        # Assert - Client should be connected (auto-connected)
        assert driver.client is not None
        assert driver.client is not original_client  # New client after auto-connect

        # Verify message was nacked (should be available again after visibility timeout)
        # Note: After nack, message becomes visible immediately (visibility timeout = 0)
        await asyncio.sleep(0.5)
        result = await driver.dequeue(TEST_QUEUE_NAME)
        assert result is not None
        assert result == task_data

        # Cleanup
        await driver.ack(TEST_QUEUE_NAME, result)
        await driver.disconnect()

    @mark.asyncio
    async def test_get_queue_size_auto_connect(self, aws_region: str) -> None:
        """Test that get_queue_size auto-connects if client is None."""
        # Arrange - Create driver, connect, enqueue, then disconnect
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        task_data = json.dumps({"task": "auto_connect_size"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)
        await driver.disconnect()

        # Act - Get queue size without explicit connect
        await asyncio.sleep(0.3)
        size = await driver.get_queue_size(TEST_QUEUE_NAME, False, False)

        # Assert - Client should be connected and size should be >= 1
        assert driver.client is not None
        assert size >= 1

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_get_queue_url_without_prefix(self, aws_region: str) -> None:
        """Test _get_queue_url when queue_url_prefix is None (API call path)."""
        # Arrange - Create driver without queue_url_prefix
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=None,  # This will trigger API call path
        )
        await driver.connect()

        # Act - Enqueue (which calls _get_queue_url internally)
        task_data = json.dumps({"task": "api_path_test"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Assert - Queue URL should be cached now
        assert TEST_QUEUE_NAME in driver._queue_urls

        # Verify message was enqueued
        result = await driver.dequeue(TEST_QUEUE_NAME)
        assert result == task_data

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_list_queues_and_stats(self, sqs_driver: SQSDriver, aws_region: str) -> None:
        """Test listing queues and getting stats via the driver."""
        # Ensure at least our test queue exists
        names = await sqs_driver.get_all_queue_names()
        assert TEST_QUEUE_NAME in names

        stats = await sqs_driver.get_queue_stats(TEST_QUEUE_NAME)
        assert stats["name"] == TEST_QUEUE_NAME
        assert isinstance(stats["depth"], int)

    @mark.asyncio
    async def test_global_stats(self, sqs_driver: SQSDriver) -> None:
        """Test that get_global_stats returns a dict with expected keys."""
        g = await sqs_driver.get_global_stats()
        assert isinstance(g, dict)
        for k in ("pending", "running", "completed", "failed", "total"):
            assert k in g

    @mark.asyncio
    async def test_unsupported_monitoring_methods(self, sqs_driver: SQSDriver) -> None:
        """Methods that SQS can't support should return empty/False values."""
        running = await sqs_driver.get_running_tasks()
        assert running == []

        tasks, total = await sqs_driver.get_tasks()
        assert tasks == [] and total == 0

        by_id = await sqs_driver.get_task_by_id("non-existent")
        assert by_id is None

        assert await sqs_driver.retry_task("nope") is False
        assert await sqs_driver.delete_task("nope") is False
        workers = await sqs_driver.get_worker_stats()
        assert workers == []


@mark.integration
class TestSQSDriverConcurrency:
    """Test concurrent operations with SQSDriver."""

    @mark.asyncio
    async def test_concurrent_enqueue(self, sqs_driver: SQSDriver) -> None:
        """Test concurrent enqueue operations."""
        # Arrange
        payloads = [{"task": f"task_{i}"} for i in range(10)]

        # Act - Enqueue concurrently
        tasks = []
        for payload in payloads:
            task_data = json.dumps(payload).encode("utf-8")
            tasks.append(sqs_driver.enqueue(TEST_QUEUE_NAME, task_data))
        await asyncio.gather(*tasks)

        # Assert
        await asyncio.sleep(0.5)  # Allow time for messages to be available
        size = await sqs_driver.get_queue_size(TEST_QUEUE_NAME, False, False)
        assert size >= len(payloads)

    @mark.asyncio
    async def test_concurrent_dequeue(self, sqs_driver: SQSDriver) -> None:
        """Test concurrent dequeue operations."""
        # Arrange
        num_messages = 5
        for i in range(num_messages):
            payload = {"task": f"task_{i}"}
            task_data = json.dumps(payload).encode("utf-8")
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        await asyncio.sleep(0.3)  # Allow messages to be available

        # Act - Dequeue concurrently
        results = await asyncio.gather(
            *[sqs_driver.dequeue(TEST_QUEUE_NAME) for _ in range(num_messages)]
        )

        # Assert
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == num_messages


@mark.integration
class TestSQSDriverEdgeCases:
    """Test edge cases and error handling."""

    @mark.asyncio
    async def test_enqueue_large_payload(self, sqs_driver: SQSDriver) -> None:
        """Test enqueuing a large payload (near SQS limit)."""
        # Arrange - SQS max message size is 256KB
        large_data = "x" * (150 * 1024)  # 150KB
        task_data = json.dumps({"task": "large_task", "data": large_data}).encode("utf-8")

        # Act
        await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)

        # Assert
        dequeued_data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued_data is not None
        dequeued_payload = json.loads(dequeued_data.decode("utf-8"))
        assert dequeued_payload["data"] == large_data

    @mark.parametrize("operation", ["ack", "nack"])
    @mark.asyncio
    async def test_invalid_receipt_handle(self, sqs_driver: SQSDriver, operation: str) -> None:
        """Test operations with invalid receipt handle are idempotent."""
        fake_receipt = b"invalid-receipt-handle"
        operation_method = getattr(sqs_driver, operation)
        await operation_method(TEST_QUEUE_NAME, fake_receipt)

    @mark.asyncio
    async def test_many_queues(self, sqs_driver: SQSDriver, aws_region: str) -> None:
        """Driver should handle many queues efficiently."""
        num_queues = 20
        payload = json.dumps({"task": "data"}).encode("utf-8")
        session = aioboto3.Session()
        client_cm = cast(
            Any,
            session.client(
                "sqs",
                endpoint_url=LOCALSTACK_ENDPOINT,
                region_name=aws_region,
                aws_access_key_id="test",
                aws_secret_access_key="test",
            ),
        )
        async with client_cm as client:
            for i in range(num_queues):
                await client.create_queue(QueueName=f"queue-{i}")
        for i in range(num_queues):
            await sqs_driver.enqueue(f"queue-{i}", payload)
        for i in range(num_queues):
            result = await sqs_driver.dequeue(f"queue-{i}")
            assert result == payload

    @mark.asyncio
    async def test_queue_name_with_special_characters(
        self, sqs_driver: SQSDriver, aws_region: str
    ) -> None:
        """Queue names with special characters should work."""
        queue_names = [
            "queue-with-dashes",
            "queue_with_underscores",
        ]  # SQS does not allow colons in queue names
        payload = json.dumps({"task": "data"}).encode("utf-8")
        session = aioboto3.Session()
        client_cm = cast(
            Any,
            session.client(
                "sqs",
                endpoint_url=LOCALSTACK_ENDPOINT,
                region_name=aws_region,
                aws_access_key_id="test",
                aws_secret_access_key="test",
            ),
        )
        async with client_cm as client:
            for queue_name in queue_names:
                await client.create_queue(QueueName=queue_name)
        for queue_name in queue_names:
            await sqs_driver.enqueue(queue_name, payload)
            result = await sqs_driver.dequeue(queue_name)
            assert result == payload

    @mark.asyncio
    async def test_reconnect_after_disconnect(self, aws_region: str) -> None:
        """Driver should be reusable after disconnect."""
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        payload1 = json.dumps({"task": "task1"}).encode("utf-8")
        payload2 = json.dumps({"task": "task2"}).encode("utf-8")
        await driver.enqueue(TEST_QUEUE_NAME, payload1)
        result1 = await driver.dequeue(TEST_QUEUE_NAME)
        assert result1 == payload1
        await driver.disconnect()
        await driver.connect()
        await driver.enqueue(TEST_QUEUE_NAME, payload2)
        result2 = await driver.dequeue(TEST_QUEUE_NAME)
        assert result2 == payload2
        await driver.disconnect()

    @mark.asyncio
    async def test_data_integrity(self, sqs_driver: SQSDriver) -> None:
        """Task data should be exactly preserved through enqueue/dequeue cycle."""
        test_cases = [
            b"simple",
            b"x" * 100_000,  # Large (100KB)
            b"with spaces",
            b"with\nnewlines\r\n",
            b"with\ttabs",
            b"\x00\x01\x02\xff",  # Binary data
            b"data\x00with\x00nulls",  # Null bytes
            b"unicode: \xc3\xa9\xc3\xa0",  # UTF-8 encoded
        ]
        for task_data in test_cases:
            await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data)
            result = await sqs_driver.dequeue(TEST_QUEUE_NAME)
            assert result == task_data, f"Failed for {task_data!r}"

    @mark.asyncio
    async def test_connect_is_idempotent(self, aws_region: str) -> None:
        """Multiple connect() calls should be safe."""
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        first_client = driver.client
        await driver.connect()
        second_client = driver.client
        assert first_client is second_client
        await driver.disconnect()

    @mark.asyncio
    async def test_disconnect_is_idempotent(self, aws_region: str) -> None:
        """Multiple disconnect() calls should be safe."""
        driver = SQSDriver(
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
            endpoint_url=LOCALSTACK_ENDPOINT,
            queue_url_prefix=f"{LOCALSTACK_ENDPOINT}/000000000000",
        )
        await driver.connect()
        await driver.disconnect()
        await driver.disconnect()
        assert driver.client is None


@mark.integration
@mark.parametrize("delay_seconds", [1, 2, 3])
class TestSQSDriverDelayedMessages:
    """Test delayed message delivery."""

    @mark.asyncio
    async def test_delayed_message(self, sqs_driver: SQSDriver, delay_seconds: int) -> None:
        """Test that delayed messages are not immediately visible."""
        # Arrange
        task_data = json.dumps({"task": "delayed_task"}).encode("utf-8")

        # Act - Enqueue with delay
        await sqs_driver.enqueue(TEST_QUEUE_NAME, task_data, delay_seconds=delay_seconds)

        # Assert - Should not be immediately available
        message = await sqs_driver.dequeue(TEST_QUEUE_NAME, poll_seconds=0)
        assert message is None

        # Wait for delay
        await asyncio.sleep(delay_seconds + 1.0)

        # Assert - Should now be available
        dequeued_data = await sqs_driver.dequeue(TEST_QUEUE_NAME)
        assert dequeued_data is not None


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
