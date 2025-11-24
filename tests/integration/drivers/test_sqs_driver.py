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
import json
from collections.abc import AsyncGenerator

import aioboto3
from pytest import fixture, main, mark

from async_task.drivers.sqs_driver import SQSDriver

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


@fixture
async def sqs_client(localstack_endpoint: str, aws_region: str) -> AsyncGenerator:
    """
    Create an aioboto3 SQS client for LocalStack.

    Note: LocalStack doesn't require real AWS credentials.
    """
    session = aioboto3.Session()
    async with session.client(
        "sqs",
        endpoint_url=localstack_endpoint,
        region_name=aws_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    ) as client:
        yield client


@fixture
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


@fixture(autouse=True)
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

    async def test_driver_initialization(self, sqs_driver: SQSDriver) -> None:
        """Test that driver initializes correctly with LocalStack."""
        assert sqs_driver.client is not None
        assert sqs_driver.region_name == TEST_REGION

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

    async def test_dequeue_empty_queue(self, sqs_driver: SQSDriver) -> None:
        """Test dequeuing from an empty queue returns None."""
        # Act
        message = await sqs_driver.dequeue(TEST_QUEUE_NAME)

        # Assert
        assert message is None

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


@mark.integration
class TestSQSDriverConcurrency:
    """Test concurrent operations with SQSDriver."""

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
    async def test_invalid_receipt_handle(self, sqs_driver: SQSDriver, operation: str) -> None:
        """Test operations with invalid receipt handle are idempotent."""
        fake_receipt = b"invalid-receipt-handle"
        operation_method = getattr(sqs_driver, operation)
        await operation_method(TEST_QUEUE_NAME, fake_receipt)

    async def test_many_queues(self, sqs_driver: SQSDriver, aws_region: str) -> None:
        """Driver should handle many queues efficiently."""
        num_queues = 20
        payload = json.dumps({"task": "data"}).encode("utf-8")
        session = aioboto3.Session()
        async with session.client(
            "sqs",
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ) as client:
            for i in range(num_queues):
                await client.create_queue(QueueName=f"queue-{i}")
        for i in range(num_queues):
            await sqs_driver.enqueue(f"queue-{i}", payload)
        for i in range(num_queues):
            result = await sqs_driver.dequeue(f"queue-{i}")
            assert result == payload

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
        async with session.client(
            "sqs",
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name=aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ) as client:
            for queue_name in queue_names:
                await client.create_queue(QueueName=queue_name)
        for queue_name in queue_names:
            await sqs_driver.enqueue(queue_name, payload)
            result = await sqs_driver.dequeue(queue_name)
            assert result == payload

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
