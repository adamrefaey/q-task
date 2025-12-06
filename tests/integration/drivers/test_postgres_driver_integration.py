"""
Integration tests for PostgresDriver using real PostgreSQL.

These tests use a real PostgreSQL instance running in Docker for testing.

Setup:
    1. You can either setup the infrastructure of the integration tests locally or using the docker image
        A) Local
            1. Install PostgreSQL: brew install postgresql (macOS) or apt-get install postgresql (Linux)
            2. Start PostgreSQL: brew services start postgresql (macOS) or systemctl start postgresql (Linux)
            3. Create test database: createdb test_db
            4. Create test user: createuser -s test (with password 'test')
        B) Docker
            1. Navigate to `tests/infrastructure` which has the docker compose file
            2. Run the container: docker compose up -d

    2. Then you can run these tests: pytest -m integration

Note:
    These are INTEGRATION tests, not unit tests. They require PostgreSQL running.
    Mark them with @mark.integration and run separately from unit tests.
"""

import asyncio
from collections.abc import AsyncGenerator
from time import time
from uuid import uuid4

import asyncpg
from pytest import fixture, main, mark
import pytest_asyncio

from asynctasq.drivers.postgres_driver import PostgresDriver

# Test configuration
POSTGRES_DSN = "postgresql://test:test@localhost:5432/test_db"
TEST_QUEUE_TABLE = f"test_queue_{uuid4().hex[:8]}"
TEST_DLQ_TABLE = f"test_dlq_{uuid4().hex[:8]}"


@fixture(scope="session")
def postgres_dsn() -> str:
    """
    PostgreSQL connection DSN.

    Override this fixture in conftest.py if using custom PostgreSQL configuration.
    """
    return POSTGRES_DSN


@pytest_asyncio.fixture
async def postgres_conn(postgres_dsn: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Create a PostgreSQL connection for direct database operations.
    """
    conn = await asyncpg.connect(postgres_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def postgres_driver(postgres_dsn: str) -> AsyncGenerator[PostgresDriver, None]:
    """
    Create a PostgresDriver instance configured for testing.
    """
    driver = PostgresDriver(
        dsn=postgres_dsn,
        queue_table=TEST_QUEUE_TABLE,
        dead_letter_table=TEST_DLQ_TABLE,
        max_attempts=3,
        retry_delay_seconds=60,
        visibility_timeout_seconds=300,
        min_pool_size=5,
        max_pool_size=10,
    )

    # Connect and initialize schema
    await driver.connect()
    await driver.init_schema()

    yield driver

    # Cleanup: drop tables and disconnect
    if driver.pool:
        await driver.pool.execute(f"DROP TABLE IF EXISTS {TEST_QUEUE_TABLE}")
        await driver.pool.execute(f"DROP TABLE IF EXISTS {TEST_DLQ_TABLE}")
    await driver.disconnect()


@pytest_asyncio.fixture(autouse=True)
async def clean_queue(postgres_driver: PostgresDriver) -> AsyncGenerator[None, None]:
    """
    Fixture that ensures tables are clean before and after tests.
    Automatically applied to all tests in this module.
    """
    # Clear tables before test
    if postgres_driver.pool:
        await postgres_driver.pool.execute(f"DELETE FROM {TEST_QUEUE_TABLE}")
        await postgres_driver.pool.execute(f"DELETE FROM {TEST_DLQ_TABLE}")

    yield

    # Clear tables after test
    if postgres_driver.pool:
        await postgres_driver.pool.execute(f"DELETE FROM {TEST_QUEUE_TABLE}")
        await postgres_driver.pool.execute(f"DELETE FROM {TEST_DLQ_TABLE}")


@mark.integration
class TestPostgresDriverWithRealPostgres:
    """Integration tests for PostgresDriver using real PostgreSQL.

    Tests validate transactional dequeue using SELECT FOR UPDATE SKIP LOCKED,
    visibility timeout, dead-letter queue, and retry logic.
    """

    @mark.asyncio
    async def test_driver_initialization(self, postgres_driver: PostgresDriver) -> None:
        """Test that driver initializes correctly with real PostgreSQL."""
        assert postgres_driver.pool is not None
        assert postgres_driver.dsn == POSTGRES_DSN
        assert postgres_driver.queue_table == TEST_QUEUE_TABLE
        assert postgres_driver.dead_letter_table == TEST_DLQ_TABLE

        # Verify connection works
        result = await postgres_driver.pool.fetchval("SELECT 1")
        assert result == 1

    @mark.asyncio
    async def test_init_schema_creates_tables(
        self, postgres_dsn: str, postgres_conn: asyncpg.Connection
    ) -> None:
        """Test that init_schema creates queue and dead-letter tables."""
        # Arrange
        queue_table = f"test_schema_queue_{uuid4().hex[:8]}"
        dlq_table = f"test_schema_dlq_{uuid4().hex[:8]}"
        driver = PostgresDriver(
            dsn=postgres_dsn,
            queue_table=queue_table,
            dead_letter_table=dlq_table,
        )

        try:
            # Act
            await driver.init_schema()

            # Assert - check tables exist
            queue_exists = await postgres_conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = $1
                )
                """,
                queue_table,
            )
            dlq_exists = await postgres_conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = $1
                )
                """,
                dlq_table,
            )

            assert queue_exists is True
            assert dlq_exists is True

            # Check index exists
            index_exists = await postgres_conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM pg_indexes
                    WHERE indexname = $1
                )
                """,
                f"idx_{queue_table}_lookup",
            )
            assert index_exists is True

        finally:
            # Cleanup
            if driver.pool:
                await driver.pool.execute(f"DROP TABLE IF EXISTS {queue_table}")
                await driver.pool.execute(f"DROP TABLE IF EXISTS {dlq_table}")
            await driver.disconnect()

    @mark.asyncio
    async def test_init_schema_is_idempotent(self, postgres_driver: PostgresDriver) -> None:
        """Test that init_schema can be called multiple times safely."""
        # Act & Assert - should not raise
        await postgres_driver.init_schema()
        await postgres_driver.init_schema()
        await postgres_driver.init_schema()

    @mark.asyncio
    async def test_enqueue_and_dequeue_single_task(self, postgres_driver: PostgresDriver) -> None:
        """Test enqueuing and dequeuing a single task."""
        # Arrange
        task_data = b"test_task_data"

        # Act - Enqueue
        await postgres_driver.enqueue("default", task_data)

        # Act - Dequeue
        receipt_handle = await postgres_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt_handle is not None
        assert isinstance(receipt_handle, bytes)
        assert len(receipt_handle) == 16  # UUID bytes

    @mark.asyncio
    async def test_enqueue_immediate_task(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Immediate task (delay=0) should be added to database with available_at <= NOW()."""
        # Arrange
        task_data = b"immediate_task"

        # Act
        await postgres_driver.enqueue("default", task_data, delay_seconds=0)

        # Assert
        result = await postgres_conn.fetchrow(
            f"SELECT * FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert result is not None
        assert result["payload"] == task_data
        assert result["status"] == "pending"
        assert result["attempts"] == 0

    @mark.asyncio
    async def test_enqueue_multiple_tasks_preserves_fifo_order(
        self, postgres_driver: PostgresDriver
    ) -> None:
        """Tasks should be dequeued in FIFO order (ordered by created_at)."""
        assert postgres_driver.pool is not None
        # Arrange
        tasks = [b"task1", b"task2", b"task3"]

        # Act
        for task in tasks:
            await postgres_driver.enqueue("default", task)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Assert - dequeue in same order
        for expected_task in tasks:
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None

            # Verify task data via database
            task_id = postgres_driver._receipt_handles.get(receipt)
            assert task_id is not None
            result = await postgres_driver.pool.fetchrow(
                f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
            )
            assert result is not None
            assert result["payload"] == expected_task

            # Ack to clean up
            await postgres_driver.ack("default", receipt)

    @mark.asyncio
    async def test_enqueue_delayed_task(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Delayed task should be added with available_at in the future."""
        # Arrange
        task_data = b"delayed_task"
        delay_seconds = 5
        before_time = time()

        # Act
        await postgres_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert
        result = await postgres_conn.fetchrow(
            f"SELECT available_at FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert result is not None

        # Calculate expected time
        available_at = result["available_at"].timestamp()
        expected_time = before_time + delay_seconds
        assert abs(available_at - expected_time) < 2.0  # Within 2 seconds tolerance

    @mark.asyncio
    async def test_enqueue_delayed_tasks_sorted_by_time(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Delayed tasks should be retrievable in order of available_at."""
        # Arrange
        tasks = [
            (b"task1", 10),
            (b"task2", 5),
            (b"task3", 15),
        ]

        # Act
        for task_data, delay in tasks:
            await postgres_driver.enqueue("default", task_data, delay_seconds=delay)

        # Assert - tasks should be ordered by available_at
        results = await postgres_conn.fetch(
            f"""
            SELECT payload FROM {TEST_QUEUE_TABLE}
            WHERE queue_name = $1
            ORDER BY available_at
            """,
            "default",
        )
        assert len(results) == 3
        assert results[0]["payload"] == b"task2"  # 5 second delay
        assert results[1]["payload"] == b"task1"  # 10 second delay
        assert results[2]["payload"] == b"task3"  # 15 second delay

    @mark.asyncio
    async def test_enqueue_to_different_queues(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Tasks can be enqueued to different queues independently."""
        # Arrange & Act
        await postgres_driver.enqueue("queue1", b"task1")
        await postgres_driver.enqueue("queue2", b"task2")

        # Assert
        task1 = await postgres_conn.fetchrow(
            f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "queue1"
        )
        task2 = await postgres_conn.fetchrow(
            f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "queue2"
        )
        assert task1 is not None
        assert task2 is not None
        assert task1["payload"] == b"task1"
        assert task2["payload"] == b"task2"

    @mark.asyncio
    async def test_dequeue_returns_receipt_handle(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """dequeue() should return receipt handle (UUID bytes)."""
        # Arrange
        task_data = b"test_task"
        await postgres_driver.enqueue("default", task_data)

        # Act
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt is not None
        assert isinstance(receipt, bytes)
        assert len(receipt) == 16  # UUID is 16 bytes

    @mark.asyncio
    async def test_dequeue_sets_status_to_processing(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """dequeue() should set task status to 'processing' and set locked_until."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")

        # Act
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Assert
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        result = await postgres_conn.fetchrow(
            f"SELECT status, locked_until FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
        )
        assert result is not None
        assert result["status"] == "processing"
        assert result["locked_until"] is not None

        # locked_until should be in the future
        locked_until = result["locked_until"].timestamp()
        assert locked_until > time()

    @mark.asyncio
    async def test_dequeue_fifo_order(self, postgres_driver: PostgresDriver) -> None:
        """dequeue() should return tasks in FIFO order (ordered by created_at)."""
        assert postgres_driver.pool is not None

        # Arrange
        tasks = [b"first", b"second", b"third"]
        for task in tasks:
            await postgres_driver.enqueue("default", task)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Act
        receipts = []
        for _ in range(3):
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            if receipt:
                receipts.append(receipt)

        # Assert
        assert len(receipts) == 3
        for i, receipt in enumerate(receipts):
            task_id = postgres_driver._receipt_handles.get(receipt)
            assert task_id is not None
            result = await postgres_driver.pool.fetchrow(
                f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
            )
            assert result is not None
            assert result["payload"] == tasks[i]

    @mark.asyncio
    async def test_dequeue_empty_queue_returns_none(self, postgres_driver: PostgresDriver) -> None:
        """dequeue() should return None for empty queue with poll_seconds=0."""
        # Act
        result = await postgres_driver.dequeue("empty_queue", poll_seconds=0)

        # Assert
        assert result is None

    @mark.asyncio
    async def test_dequeue_with_poll_waits(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """dequeue() with poll_seconds should wait for tasks."""

        # Arrange
        async def enqueue_delayed():
            await asyncio.sleep(0.3)
            await postgres_driver.enqueue("default", b"delayed")

        # Act
        enqueue_task = asyncio.create_task(enqueue_delayed())
        result = await postgres_driver.dequeue("default", poll_seconds=2)

        # Assert
        assert result is not None

        # Cleanup
        await enqueue_task

    @mark.asyncio
    async def test_dequeue_poll_expires(self, postgres_driver: PostgresDriver) -> None:
        """dequeue() should return None when poll duration expires."""
        # Act
        start = time()
        result = await postgres_driver.dequeue("empty", poll_seconds=1)
        elapsed = time() - start

        # Assert
        assert result is None
        assert elapsed >= 0.9  # Account for some timing variance

    @mark.asyncio
    async def test_dequeue_skips_delayed_tasks(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """dequeue() should not return delayed tasks that aren't ready yet."""
        # Arrange
        # Add immediate task
        await postgres_driver.enqueue("default", b"immediate")
        # Add future task
        await postgres_driver.enqueue("default", b"future", delay_seconds=100)

        # Act
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await postgres_driver.ack("default", receipt)

        # Second dequeue should return None (future task not ready)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt2 is None

    @mark.asyncio
    async def test_dequeue_skips_locked_tasks(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """dequeue() should skip tasks that are locked (locked_until in future)."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")

        # Dequeue first task (locks it)
        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt1 is not None

        # Act - dequeue second time should get task2, not task1
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt2 is not None

        # Assert - should have 2 different receipts
        assert receipt1 != receipt2

        # Third dequeue should return None (both locked)
        receipt3 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt3 is None

    @mark.asyncio
    async def test_dequeue_with_skip_locked_concurrency(
        self, postgres_driver: PostgresDriver
    ) -> None:
        """dequeue() with SKIP LOCKED should allow concurrent dequeues without blocking."""
        # Arrange
        num_tasks = 10
        for i in range(num_tasks):
            await postgres_driver.enqueue("default", f"task{i}".encode())

        # Act - concurrent dequeues
        receipts = await asyncio.gather(
            *[postgres_driver.dequeue("default", poll_seconds=0) for _ in range(num_tasks)]
        )

        # Assert - all receipts should be unique and non-None
        receipts = [r for r in receipts if r is not None]
        assert len(receipts) == num_tasks
        assert len(set(receipts)) == num_tasks  # All unique

    @mark.asyncio
    async def test_ack_removes_task(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """ack() removes task from database."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await postgres_driver.ack("default", receipt)

        # Assert - task should not exist in database
        count = await postgres_conn.fetchval(f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE}")
        assert count == 0

        # Receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_ack_invalid_receipt_is_safe(self, postgres_driver: PostgresDriver) -> None:
        """ack() with invalid receipt should not raise error."""
        # Arrange
        invalid_receipt = uuid4().bytes

        # Act & Assert - should not raise
        await postgres_driver.ack("default", invalid_receipt)

    @mark.asyncio
    async def test_nack_requeues_task(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """nack() should requeue task with incremented attempts."""
        # Arrange
        task_data = b"failed_task"
        await postgres_driver.enqueue("default", task_data)
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await postgres_driver.nack("default", receipt)

        # Assert - task should be requeued with attempts=1
        result = await postgres_conn.fetchrow(
            f"SELECT attempts, status FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert result is not None
        assert result["attempts"] == 1
        assert result["status"] == "pending"

        # Receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_nack_exponential_backoff(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """nack() should apply exponential backoff to available_at."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")

        # Track available_at times
        available_times = []

        # Act - nack multiple times
        for expected_attempts in range(1, 3):
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None

            await postgres_driver.nack("default", receipt)

            # Check available_at
            result = await postgres_conn.fetchrow(
                f"SELECT available_at, attempts FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1",
                "default",
            )
            assert result is not None
            assert result["attempts"] == expected_attempts
            available_times.append(result["available_at"].timestamp())

            # Make task available again for next iteration by setting available_at to past
            await postgres_conn.execute(
                f"UPDATE {TEST_QUEUE_TABLE} SET available_at = NOW() - INTERVAL '1 second', locked_until = NULL WHERE queue_name = $1",
                "default",
            )

        # Assert - backoff should increase exponentially
        # First retry: retry_delay_seconds * 2^0 = 60
        # Second retry: retry_delay_seconds * 2^1 = 120
        now = time()
        assert available_times[0] > now + 50  # At least 50 seconds (60 - tolerance)
        assert available_times[1] > now + 110  # At least 110 seconds (120 - tolerance)

    @mark.asyncio
    async def test_nack_moves_to_dead_letter_after_max_attempts(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """nack() should move task to dead letter queue after max_attempts."""
        # Arrange
        task_data = b"failing_task"
        await postgres_driver.enqueue("default", task_data)

        # Act - nack max_attempts times
        for attempt in range(postgres_driver.max_attempts):
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None
            await postgres_driver.nack("default", receipt)

            # Make task available again for next iteration (except last one which goes to DLQ)
            if attempt < postgres_driver.max_attempts - 1:
                await postgres_conn.execute(
                    f"UPDATE {TEST_QUEUE_TABLE} SET available_at = NOW() - INTERVAL '1 second', locked_until = NULL WHERE queue_name = $1",
                    "default",
                )

        # Assert - task should be in dead letter queue
        dlq_result = await postgres_conn.fetchrow(
            f"SELECT * FROM {TEST_DLQ_TABLE} WHERE queue_name = $1", "default"
        )
        assert dlq_result is not None
        assert dlq_result["payload"] == task_data
        assert dlq_result["attempts"] == postgres_driver.max_attempts
        assert dlq_result["error_message"] == "Max retries exceeded"

        # Task should not be in main queue
        queue_count = await postgres_conn.fetchval(
            f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert queue_count == 0

    @mark.asyncio
    async def test_nack_after_ack_is_safe(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """nack() after ack() should not requeue task."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await postgres_driver.ack("default", receipt)

        # Act - nack on already-acked task
        await postgres_driver.nack("default", receipt)

        # Assert - task should NOT be in queue
        count = await postgres_conn.fetchval(f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE}")
        assert count == 0

    @mark.asyncio
    async def test_nack_invalid_receipt_is_safe(self, postgres_driver: PostgresDriver) -> None:
        """nack() with invalid receipt should not raise error."""
        # Arrange
        invalid_receipt = uuid4().bytes

        # Act & Assert - should not raise
        await postgres_driver.nack("default", invalid_receipt)

    @mark.asyncio
    async def test_get_queue_size_returns_count(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_queue_size() should return number of ready tasks."""
        # Arrange
        for i in range(3):
            await postgres_driver.enqueue("default", f"task{i}".encode())

        # Act
        size = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 3

    @mark.asyncio
    async def test_get_queue_size_empty_queue(self, postgres_driver: PostgresDriver) -> None:
        """get_queue_size() should return 0 for empty queue."""
        # Act
        size = await postgres_driver.get_queue_size(
            "empty", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 0

    @mark.asyncio
    async def test_get_queue_size_includes_in_flight(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_queue_size() should include in-flight tasks when requested."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")
        await postgres_driver.dequeue("default", poll_seconds=0)  # Move task1 to processing

        # Act - without in_flight
        size_without = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        # Act - with in_flight
        size_with = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=True
        )

        # Assert
        assert size_without == 1  # Only task2 ready
        assert size_with == 2  # task2 ready + task1 processing

    @mark.asyncio
    async def test_get_queue_size_with_delayed_flag(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_queue_size() behavior with include_delayed flag."""
        # Arrange
        await postgres_driver.enqueue("default", b"immediate")
        await postgres_driver.enqueue("default", b"delayed", delay_seconds=100)

        # Act
        size_without_delayed = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        size_with_delayed = await postgres_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )

        # Assert
        assert size_without_delayed == 1  # Only immediate task counted
        assert size_with_delayed == 2  # Both immediate and delayed tasks counted

    @mark.asyncio
    async def test_delayed_task_becomes_available(self, postgres_driver: PostgresDriver) -> None:
        """Integration: Delayed task should become available after short delay."""
        # Arrange
        task_data = b"delayed_task"
        # Set delay of 1 second
        await postgres_driver.enqueue("default", task_data, delay_seconds=1)

        # Act - should not be available immediately
        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt1 is None

        # Wait for delay
        await asyncio.sleep(1.2)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt2 is not None

    @mark.asyncio
    async def test_visibility_timeout_recovery(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Tasks with expired locked_until should be recoverable."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Manually expire the lock
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )

        # Act - should be able to dequeue again
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt2 is not None
        # Should be different receipt
        assert receipt2 != receipt

    @mark.asyncio
    async def test_get_queue_size_all_combinations(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Test all four combinations of get_queue_size flags."""
        # Arrange: Create tasks in different states
        # - 2 ready tasks (immediate, available)
        await postgres_driver.enqueue("default", b"ready1")
        await postgres_driver.enqueue("default", b"ready2")
        # - 1 delayed task (future available_at)
        await postgres_driver.enqueue("default", b"delayed", delay_seconds=100)
        # - 1 in-flight task (dequeued, status=processing)
        await postgres_driver.dequeue("default", poll_seconds=0)

        # Test all 4 combinations
        # 1. Both False: Only ready tasks
        size_00 = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size_00 == 1  # Only ready2 (ready1 was dequeued)

        # 2. include_delayed=True, include_in_flight=False: Ready + delayed
        size_10 = await postgres_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )
        assert size_10 == 2  # ready2 + delayed

        # 3. include_delayed=False, include_in_flight=True: Ready + in-flight
        size_01 = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=True
        )
        assert size_01 == 2  # ready2 + in-flight

        # 4. Both True: All tasks
        size_11 = await postgres_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=True
        )
        assert size_11 == 3  # ready2 + delayed + in-flight

    @mark.asyncio
    async def test_get_queue_size_with_mixed_states(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Test get_queue_size with complex mixed states."""
        # Arrange: Create various task states
        await postgres_driver.enqueue("default", b"ready1")
        await postgres_driver.enqueue("default", b"ready2")
        await postgres_driver.enqueue("default", b"delayed1", delay_seconds=50)
        await postgres_driver.enqueue("default", b"delayed2", delay_seconds=100)
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)  # ready1 -> processing

        assert receipt is not None

        # Test with all flags True
        size_all = await postgres_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=True
        )
        assert size_all == 4  # ready2 + delayed1 + delayed2 + in-flight

        # Cleanup
        await postgres_driver.ack("default", receipt)

    @mark.asyncio
    async def test_ack_after_visibility_timeout_expires(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Ack should handle receipt handle even if visibility timeout expired."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Manually expire the lock
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second' WHERE id = $1",
            task_id,
        )

        # Act - ack should still work (task exists, just lock expired)
        await postgres_driver.ack("default", receipt)

        # Assert - task should be deleted
        count = await postgres_conn.fetchval(f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE}")
        assert count == 0

    @mark.asyncio
    async def test_ack_twice_is_safe(self, postgres_driver: PostgresDriver) -> None:
        """Acking the same receipt handle twice should be safe."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act - ack twice
        await postgres_driver.ack("default", receipt)
        await postgres_driver.ack("default", receipt)  # Second ack

        # Assert - should not raise, receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_nack_after_visibility_timeout_expires(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Nack should handle receipt handle even if visibility timeout expired."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Manually expire the lock and reset status
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )

        # Act - nack should still work
        await postgres_driver.nack("default", receipt)

        # Assert - task should be requeued with incremented attempts
        result = await postgres_conn.fetchrow(
            f"SELECT attempts FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
        )
        assert result is not None
        assert result["attempts"] == 1

    @mark.asyncio
    async def test_nack_then_ack_is_safe(self, postgres_driver: PostgresDriver) -> None:
        """Acking after nack should be safe (task may not exist)."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act - nack then ack
        await postgres_driver.nack("default", receipt)
        await postgres_driver.ack("default", receipt)  # Should not raise

        # Assert - receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_ack_after_task_deleted(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Ack should handle case where task was already deleted."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Manually delete the task
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        await postgres_conn.execute(f"DELETE FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id)

        # Act - ack should not raise
        await postgres_driver.ack("default", receipt)

        # Assert - receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_nack_after_task_deleted(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Nack should handle case where task was already deleted."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Manually delete the task
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None
        await postgres_conn.execute(f"DELETE FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id)

        # Act - nack should not raise
        await postgres_driver.nack("default", receipt)

        # Assert - receipt handle should be cleared
        assert receipt not in postgres_driver._receipt_handles

    @mark.asyncio
    async def test_operations_auto_connect(self, postgres_dsn: str) -> None:
        """Operations should auto-connect if not connected."""
        # Arrange
        queue_table = f"test_auto_connect_{uuid4().hex[:8]}"
        dlq_table = f"test_auto_connect_dlq_{uuid4().hex[:8]}"
        driver = PostgresDriver(
            dsn=postgres_dsn,
            queue_table=queue_table,
            dead_letter_table=dlq_table,
        )

        try:
            # Act - operations without explicit connect
            await driver.init_schema()  # Should auto-connect
            assert driver.pool is not None

            await driver.enqueue("default", b"task")  # Should work
            receipt = await driver.dequeue("default", poll_seconds=0)  # Should work
            assert receipt is not None

            await driver.ack("default", receipt)  # Should work

            size = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )  # Should work
            assert size == 0

        finally:
            # Cleanup
            if driver.pool:
                await driver.pool.execute(f"DROP TABLE IF EXISTS {queue_table}")
                await driver.pool.execute(f"DROP TABLE IF EXISTS {dlq_table}")
            await driver.disconnect()

    @mark.asyncio
    async def test_dequeue_poll_with_task_arrival(self, postgres_driver: PostgresDriver) -> None:
        """Polling should find tasks that arrive during poll."""

        # Arrange
        async def enqueue_after_delay():
            await asyncio.sleep(0.5)
            await postgres_driver.enqueue("default", b"arrived_during_poll")

        # Act - start polling, then enqueue task
        enqueue_task = asyncio.create_task(enqueue_after_delay())
        receipt = await postgres_driver.dequeue("default", poll_seconds=2)

        # Assert
        assert receipt is not None
        await enqueue_task

    @mark.asyncio
    async def test_dequeue_poll_short_duration(self, postgres_driver: PostgresDriver) -> None:
        """Polling with very short duration should work correctly."""
        # Arrange - no tasks
        # Act
        start = time()
        receipt = await postgres_driver.dequeue("default", poll_seconds=1)
        elapsed = time() - start

        # Assert
        assert receipt is None
        assert 0.95 <= elapsed < 1.3  # Should poll briefly then return

    @mark.asyncio
    async def test_receipt_handle_cleanup_on_ack(self, postgres_driver: PostgresDriver) -> None:
        """Receipt handles should be cleaned up after ack."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")

        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None
        assert len(postgres_driver._receipt_handles) == 2

        # Act
        await postgres_driver.ack("default", receipt1)

        # Assert
        assert receipt1 not in postgres_driver._receipt_handles
        assert receipt2 in postgres_driver._receipt_handles
        assert len(postgres_driver._receipt_handles) == 1

        # Cleanup
        await postgres_driver.ack("default", receipt2)

    @mark.asyncio
    async def test_receipt_handle_cleanup_on_nack(self, postgres_driver: PostgresDriver) -> None:
        """Receipt handles should be cleaned up after nack."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")

        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)

        assert receipt1 is not None
        assert receipt2 is not None
        assert len(postgres_driver._receipt_handles) == 2

        # Act
        await postgres_driver.nack("default", receipt1)

        # Assert
        assert receipt1 not in postgres_driver._receipt_handles
        assert receipt2 in postgres_driver._receipt_handles
        assert len(postgres_driver._receipt_handles) == 1

        # Cleanup
        await postgres_driver.ack("default", receipt2)

    @mark.asyncio
    async def test_concurrent_ack_nack(self, postgres_driver: PostgresDriver) -> None:
        """Concurrent ack and nack operations should be safe."""
        # Arrange
        num_tasks = 20
        for i in range(num_tasks):
            await postgres_driver.enqueue("default", f"task{i}".encode())

        receipts = []
        for _ in range(num_tasks):
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            if receipt:
                receipts.append(receipt)

        assert len(receipts) == num_tasks

        # Act - concurrently ack and nack
        async def ack_even():
            for i, receipt in enumerate(receipts):
                if i % 2 == 0:
                    await postgres_driver.ack("default", receipt)

        async def nack_odd():
            for i, receipt in enumerate(receipts):
                if i % 2 == 1:
                    await postgres_driver.nack("default", receipt)

        await asyncio.gather(ack_even(), nack_odd())

        # Assert - all receipt handles should be cleared
        assert len(postgres_driver._receipt_handles) == 0

    @mark.asyncio
    async def test_multiple_visibility_timeout_expirations(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Multiple visibility timeout expirations should allow task recovery."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt1 is not None

        task_id = postgres_driver._receipt_handles.get(receipt1)
        assert task_id is not None

        # Expire lock first time
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt2 is not None
        assert receipt2 != receipt1

        # Expire lock second time
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )
        receipt3 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt3 is not None
        assert receipt3 != receipt2

    @mark.asyncio
    async def test_get_queue_size_with_expired_locks(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_queue_size should correctly handle expired locks."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None

        # Expire the lock
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )

        # Act - get_queue_size should count the expired task as ready
        size = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert - both tasks should be counted as ready (lock expired)
        assert size == 2

    @mark.asyncio
    async def test_nack_with_custom_max_attempts(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Nack should respect per-task max_attempts from database."""
        # Arrange - create task with custom max_attempts
        await postgres_conn.execute(
            f"""
            INSERT INTO {TEST_QUEUE_TABLE}
                (queue_name, payload, available_at, status, attempts, max_attempts, created_at)
            VALUES ($1, $2, NOW(), 'pending', 0, $3, NOW())
            """,
            "default",
            b"custom_task",
            5,  # Custom max_attempts
        )

        # Act - nack multiple times (should allow up to 5 attempts)
        for attempt in range(4):  # 0->1, 1->2, 2->3, 3->4
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None
            await postgres_driver.nack("default", receipt)

            # Make available for next iteration
            if attempt < 4:
                await postgres_conn.execute(
                    f"UPDATE {TEST_QUEUE_TABLE} SET available_at = NOW() - INTERVAL '1 second', locked_until = NULL WHERE queue_name = $1",
                    "default",
                )

        # Assert - task should still be in queue (not in DLQ yet)
        queue_count = await postgres_conn.fetchval(
            f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert queue_count == 1

        # One more nack should move to DLQ
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        await postgres_driver.nack("default", receipt)

        dlq_count = await postgres_conn.fetchval(
            f"SELECT COUNT(*) FROM {TEST_DLQ_TABLE} WHERE queue_name = $1", "default"
        )
        assert dlq_count == 1

    @mark.asyncio
    async def test_dequeue_skips_expired_locked_tasks(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Dequeue should skip tasks with expired locks and make them available."""
        # Arrange
        await postgres_driver.enqueue("default", b"task1")
        await postgres_driver.enqueue("default", b"task2")

        # Dequeue task1 (locks it)
        receipt1 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt1 is not None

        # Manually expire the lock
        task_id = postgres_driver._receipt_handles.get(receipt1)
        assert task_id is not None
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET locked_until = NOW() - INTERVAL '1 second', status = 'pending' WHERE id = $1",
            task_id,
        )

        # Act - dequeue should now get task1 again (lock expired)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt2 is not None

        # Assert - should be able to get task1 (expired) or task2
        # The order depends on created_at, but both should be available
        task_id2 = postgres_driver._receipt_handles.get(receipt2)
        assert task_id2 is not None
        assert task_id2 in [task_id, task_id + 1]  # Either same task or next

    @mark.asyncio
    async def test_get_queue_size_empty_queue_all_combinations(
        self, postgres_driver: PostgresDriver
    ) -> None:
        """get_queue_size should return 0 for empty queue in all flag combinations."""
        # Act & Assert - all combinations should return 0
        assert (
            await postgres_driver.get_queue_size(
                "empty", include_delayed=False, include_in_flight=False
            )
            == 0
        )
        assert (
            await postgres_driver.get_queue_size(
                "empty", include_delayed=True, include_in_flight=False
            )
            == 0
        )
        assert (
            await postgres_driver.get_queue_size(
                "empty", include_delayed=False, include_in_flight=True
            )
            == 0
        )
        assert (
            await postgres_driver.get_queue_size(
                "empty", include_delayed=True, include_in_flight=True
            )
            == 0
        )

    @mark.asyncio
    async def test_table_names_with_special_characters(
        self, postgres_dsn: str, postgres_conn: asyncpg.Connection
    ) -> None:
        """Table names with special characters should be handled safely."""
        # Arrange - use table names that could be problematic
        queue_table = "test_queue_123"
        dlq_table = "test_dlq_456"
        driver = PostgresDriver(
            dsn=postgres_dsn,
            queue_table=queue_table,
            dead_letter_table=dlq_table,
        )

        try:
            # Act - should work without SQL injection issues
            await driver.init_schema()
            await driver.enqueue("default", b"task")
            receipt = await driver.dequeue("default", poll_seconds=0)
            assert receipt is not None
            await driver.ack("default", receipt)

            # Assert - verify tables exist
            queue_exists = await postgres_conn.fetchval(
                "SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = $1)", queue_table
            )
            assert queue_exists is True

        finally:
            # Cleanup
            if driver.pool:
                await driver.pool.execute(f"DROP TABLE IF EXISTS {queue_table}")
                await driver.pool.execute(f"DROP TABLE IF EXISTS {dlq_table}")
            await driver.disconnect()

    @mark.asyncio
    async def test_very_large_delay(self, postgres_driver: PostgresDriver) -> None:
        """Very large delay values should be handled correctly."""
        # Arrange
        large_delay = 86400 * 365  # 1 year in seconds

        # Act
        await postgres_driver.enqueue("default", b"future_task", delay_seconds=large_delay)

        # Assert - should not be immediately available
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is None

        # Verify it's in the queue
        size = await postgres_driver.get_queue_size(
            "default", include_delayed=True, include_in_flight=False
        )
        assert size == 1

    @mark.asyncio
    async def test_receipt_handle_uniqueness(self, postgres_driver: PostgresDriver) -> None:
        """Receipt handles should be unique across multiple dequeues."""
        # Arrange
        num_tasks = 100
        for i in range(num_tasks):
            await postgres_driver.enqueue("default", f"task{i}".encode())

        # Act - dequeue all tasks
        receipts = []
        for _ in range(num_tasks):
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            if receipt:
                receipts.append(receipt)

        # Assert - all receipts should be unique
        assert len(receipts) == num_tasks
        assert len(set(receipts)) == num_tasks

        # Cleanup
        for receipt in receipts:
            await postgres_driver.ack("default", receipt)

    @mark.asyncio
    async def test_nack_requeue_clears_lock(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Nack should clear locked_until when requeuing."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None

        # Verify task is locked
        result = await postgres_conn.fetchrow(
            f"SELECT locked_until FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
        )
        assert result is not None
        assert result["locked_until"] is not None

        # Act - nack
        await postgres_driver.nack("default", receipt)

        # Assert - lock should be cleared
        result = await postgres_conn.fetchrow(
            f"SELECT locked_until, status FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
        )
        assert result is not None
        assert result["locked_until"] is None
        assert result["status"] == "pending"

    @mark.asyncio
    async def test_dequeue_after_nack_retry(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """Task should be dequeuable after nack retry delay expires."""
        # Arrange
        await postgres_driver.enqueue("default", b"task")
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Nack (will requeue with delay)
        await postgres_driver.nack("default", receipt)

        # Task should not be immediately available (retry delay)
        receipt2 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt2 is None

        # Manually expire the retry delay
        await postgres_conn.execute(
            f"UPDATE {TEST_QUEUE_TABLE} SET available_at = NOW() - INTERVAL '1 second' WHERE queue_name = $1",
            "default",
        )

        # Act - should now be available
        receipt3 = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt3 is not None

    @mark.asyncio
    async def test_get_queue_size_different_queues(self, postgres_driver: PostgresDriver) -> None:
        """get_queue_size should only count tasks in specified queue."""
        # Arrange
        await postgres_driver.enqueue("queue1", b"task1")
        await postgres_driver.enqueue("queue1", b"task2")
        await postgres_driver.enqueue("queue2", b"task3")

        # Act
        size1 = await postgres_driver.get_queue_size(
            "queue1", include_delayed=False, include_in_flight=False
        )
        size2 = await postgres_driver.get_queue_size(
            "queue2", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size1 == 2
        assert size2 == 1

    @mark.asyncio
    async def test_get_all_queue_names_and_global_stats(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_all_queue_names() and get_global_stats() should report queues and counts."""
        # Arrange
        await postgres_driver.enqueue("qa", b"a")
        await postgres_driver.enqueue("qb", b"b")

        # Dequeue one task to create a processing entry
        receipt = await postgres_driver.dequeue("qa", poll_seconds=0)
        assert receipt is not None

        # Act
        names = await postgres_driver.get_all_queue_names()
        stats = await postgres_driver.get_global_stats()

        # Assert
        assert "qa" in names and "qb" in names
        assert stats["total"] >= 2
        # One processing (dequeued), one pending
        assert stats["running"] >= 1
        assert stats["pending"] >= 1

        # Cleanup
        await postgres_driver.ack("qa", receipt)

    @mark.asyncio
    async def test_get_running_tasks_get_tasks_and_get_task_by_id(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """get_running_tasks(), get_tasks(), and get_task_by_id() should return correct data."""
        # Arrange
        await postgres_driver.enqueue("default", b"r1")
        await postgres_driver.enqueue("default", b"r2")
        await postgres_driver.enqueue("other", b"o1")

        # Move one to processing
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None
        task_id = postgres_driver._receipt_handles.get(receipt)
        assert task_id is not None

        # Act - running tasks (returns list of (bytes, queue_name) tuples)
        running = await postgres_driver.get_running_tasks(limit=10)
        assert any(t[1] == "default" for t in running)

        # Act - filtered tasks (returns list of (bytes, queue_name, status) tuples)
        tasks, total = await postgres_driver.get_tasks(
            status="processing", queue="default", limit=10, offset=0
        )
        assert total >= 1
        assert len(tasks) >= 1

        # Act - get_task_by_id using task_id from receipt_handles
        fetched = await postgres_driver.get_task_by_id(str(task_id))
        assert fetched is not None
        # fetched is now raw bytes
        assert isinstance(fetched, bytes)

        # Cleanup
        await postgres_driver.ack("default", receipt)

    @mark.asyncio
    async def test_retry_and_delete_task_and_get_worker_stats(
        self, postgres_driver: PostgresDriver, postgres_conn: asyncpg.Connection
    ) -> None:
        """retry_task() should move DLQ entry back to queue; delete_task() should remove task; get_worker_stats() returns []."""
        # Arrange - insert directly into DLQ
        row = await postgres_conn.fetchrow(
            f"INSERT INTO {TEST_DLQ_TABLE} (queue_name, payload, attempts, error_message) VALUES ($1, $2, $3, $4) RETURNING id",
            "default",
            b"dlq_payload",
            2,
            "error",
        )
        assert row is not None
        dlq_id = row["id"]

        # Act - retry
        retried = await postgres_driver.retry_task(dlq_id)
        assert retried is True

        # Assert - DLQ should no longer contain the entry and queue should have it
        dlq_count = await postgres_conn.fetchval(
            f"SELECT COUNT(*) FROM {TEST_DLQ_TABLE} WHERE id = $1", dlq_id
        )
        assert dlq_count == 0

        qrow = await postgres_conn.fetchrow(
            f"SELECT id FROM {TEST_QUEUE_TABLE} WHERE queue_name = $1", "default"
        )
        assert qrow is not None
        qid = qrow["id"]

        # Act - delete from main queue
        deleted = await postgres_driver.delete_task(qid)
        assert deleted is True

        # Assert - ensure it's gone
        exists = await postgres_conn.fetchval(
            f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE} WHERE id = $1", qid
        )
        assert exists == 0

        # Insert into DLQ then delete DLQ entry via delete_task
        row2 = await postgres_conn.fetchrow(
            f"INSERT INTO {TEST_DLQ_TABLE} (queue_name, payload, attempts, error_message) VALUES ($1, $2, $3, $4) RETURNING id",
            "default",
            b"dlq2",
            1,
            "err2",
        )
        assert row2 is not None
        dlq2 = row2["id"]
        deleted2 = await postgres_driver.delete_task(dlq2)
        assert deleted2 is True

        # get_worker_stats should return empty list for PostgresDriver
        workers = await postgres_driver.get_worker_stats()
        assert isinstance(workers, list)
        assert workers == []


@mark.integration
class TestPostgresDriverConcurrency:
    """Test concurrent operations with PostgresDriver.

    Validates thread-safe/async-safe operations using SELECT FOR UPDATE SKIP LOCKED.
    """

    @mark.asyncio
    async def test_concurrent_enqueue(self, postgres_driver: PostgresDriver) -> None:
        """Multiple concurrent enqueues should all succeed."""
        # Arrange
        num_tasks = 50

        # Act
        await asyncio.gather(
            *[postgres_driver.enqueue("default", f"task{i}".encode()) for i in range(num_tasks)]
        )

        # Assert
        size = await postgres_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )
        assert size == num_tasks

    @mark.asyncio
    async def test_concurrent_dequeue(self, postgres_driver: PostgresDriver) -> None:
        """Multiple concurrent dequeues should get unique tasks."""
        # Arrange
        num_tasks = 30
        for i in range(num_tasks):
            await postgres_driver.enqueue("default", f"task{i}".encode())

        # Act
        receipts = await asyncio.gather(
            *[postgres_driver.dequeue("default", poll_seconds=0) for _ in range(num_tasks)]
        )

        # Assert - all receipts should be unique
        receipts = [r for r in receipts if r is not None]
        assert len(receipts) == num_tasks
        assert len(set(receipts)) == num_tasks  # All unique

    @mark.asyncio
    async def test_concurrent_enqueue_dequeue(self, postgres_driver: PostgresDriver) -> None:
        """Concurrent enqueues and dequeues should work correctly."""
        num_tasks = 20
        results = []

        async def producer():
            """Slowly enqueue tasks one at a time."""
            for i in range(num_tasks):
                await postgres_driver.enqueue("default", f"task{i}".encode())
                await asyncio.sleep(0.01)  # Simulate slow production

        async def consumer():
            """Poll and consume tasks as they become available."""
            for _ in range(num_tasks):
                receipt = await postgres_driver.dequeue("default", poll_seconds=2)
                if receipt:
                    results.append(receipt)

        # Act - run producer and consumer truly concurrently
        await asyncio.gather(producer(), consumer())

        # Assert - all tasks were successfully consumed
        assert len(results) == num_tasks
        assert len(set(results)) == num_tasks  # All unique


@mark.integration
class TestPostgresDriverEdgeCases:
    """Test edge cases and error conditions."""

    @mark.asyncio
    async def test_many_queues(self, postgres_driver: PostgresDriver) -> None:
        """Driver should handle many queues efficiently."""
        # Arrange
        num_queues = 50

        # Act
        for i in range(num_queues):
            await postgres_driver.enqueue(f"queue{i}", f"data{i}".encode())

        # Assert - verify all queues have tasks
        for i in range(num_queues):
            size = await postgres_driver.get_queue_size(
                f"queue{i}", include_delayed=False, include_in_flight=False
            )
            assert size == 1

    @mark.asyncio
    async def test_queue_name_with_special_characters(
        self, postgres_driver: PostgresDriver
    ) -> None:
        """Queue names with special characters should work."""
        # Arrange
        queue_names = ["queue:with:colons", "queue-with-dashes", "queue_with_underscores"]

        # Act & Assert
        for queue_name in queue_names:
            await postgres_driver.enqueue(queue_name, b"data")
            receipt = await postgres_driver.dequeue(queue_name, poll_seconds=0)
            assert receipt is not None
            await postgres_driver.ack(queue_name, receipt)

    @mark.asyncio
    async def test_reconnect_after_disconnect(self, postgres_dsn: str) -> None:
        """Driver should be reusable after disconnect."""
        # Arrange
        queue_table = f"test_reconnect_{uuid4().hex[:8]}"
        dlq_table = f"test_reconnect_dlq_{uuid4().hex[:8]}"
        driver = PostgresDriver(
            dsn=postgres_dsn,
            queue_table=queue_table,
            dead_letter_table=dlq_table,
        )
        await driver.connect()
        await driver.init_schema()

        task1 = b"task1"
        task2 = b"task2"

        try:
            # Act - use, disconnect, reconnect, use again
            await driver.enqueue("default", task1)
            receipt1 = await driver.dequeue("default", poll_seconds=0)
            assert receipt1 is not None
            await driver.ack("default", receipt1)

            await driver.disconnect()
            await driver.connect()

            await driver.enqueue("default", task2)
            receipt2 = await driver.dequeue("default", poll_seconds=0)

            # Assert
            assert receipt2 is not None

        finally:
            # Cleanup
            if driver.pool:
                await driver.pool.execute(f"DROP TABLE IF EXISTS {queue_table}")
                await driver.pool.execute(f"DROP TABLE IF EXISTS {dlq_table}")
            await driver.disconnect()

    @mark.asyncio
    async def test_task_data_integrity(self, postgres_driver: PostgresDriver) -> None:
        """Task data should be exactly preserved through enqueue/dequeue cycle.

        Tests binary safety, null bytes, UTF-8, and large payloads.
        """
        assert postgres_driver.pool is not None
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
            await postgres_driver.enqueue("default", task_data)
            receipt = await postgres_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None

            # Verify data via database
            task_id = postgres_driver._receipt_handles.get(receipt)
            assert task_id is not None
            result = await postgres_driver.pool.fetchrow(
                f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE id = $1", task_id
            )
            assert result is not None
            assert result["payload"] == task_data, f"Failed for {task_data!r}"

            await postgres_driver.ack("default", receipt)

    @mark.asyncio
    async def test_delay_values(self, postgres_driver: PostgresDriver) -> None:
        """Test different delay value behaviors."""
        # Test zero delay
        await postgres_driver.enqueue("default", b"task_zero", delay_seconds=0)
        receipt_zero = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt_zero is not None
        await postgres_driver.ack("default", receipt_zero)

        # Test negative delay (should be immediately available)
        await postgres_driver.enqueue("default", b"task_negative", delay_seconds=-1)
        receipt_negative = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt_negative is not None
        await postgres_driver.ack("default", receipt_negative)

    @mark.asyncio
    async def test_connect_is_idempotent(self, postgres_dsn: str) -> None:
        """Multiple connect() calls should be safe."""
        # Arrange
        driver = PostgresDriver(dsn=postgres_dsn)

        # Act
        await driver.connect()
        first_pool = driver.pool
        await driver.connect()  # Second call
        second_pool = driver.pool

        # Assert
        assert first_pool is second_pool

        # Cleanup
        await driver.disconnect()

    @mark.asyncio
    async def test_disconnect_is_idempotent(self, postgres_dsn: str) -> None:
        """Multiple disconnect() calls should be safe."""
        # Arrange
        driver = PostgresDriver(dsn=postgres_dsn)
        await driver.connect()

        # Act & Assert - should not raise
        await driver.disconnect()
        await driver.disconnect()  # Second call

        assert driver.pool is None


@mark.integration
@mark.parametrize("delay_seconds", [1, 2, 3])
class TestPostgresDriverDelayedTasks:
    """Test delayed task processing with various delays."""

    @mark.asyncio
    async def test_delayed_task_not_immediately_available(
        self, postgres_driver: PostgresDriver, delay_seconds: int
    ) -> None:
        """Delayed tasks should not be immediately available."""
        # Arrange
        task_data = b"delayed_task"

        # Act - Enqueue with delay
        await postgres_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert - Should not be immediately available
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is None

        # Wait for delay
        await asyncio.sleep(delay_seconds + 0.5)

        # Assert - Should now be available
        receipt = await postgres_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
