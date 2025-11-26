"""
Integration tests for MySQLDriver using real MySQL.

These tests use a real MySQL instance running in Docker for testing.

Setup:
    1. You can either setup the infrastructure of the integration tests locally or using the docker image
        A) Local
            1. Install MySQL: brew install mysql (macOS) or apt-get install mysql-server (Linux)
            2. Start MySQL: brew services start mysql (macOS) or systemctl start mysql (Linux)
            3. Create test database: mysql -u root -e "CREATE DATABASE test_db;"
            4. Create test user: mysql -u root -e "CREATE USER 'test'@'localhost' IDENTIFIED BY 'test'; GRANT ALL ON test_db.* TO 'test'@'localhost';"
        B) Docker
            1. Navigate to `tests/infrastructure` which has the docker compose file
            2. Run the container: docker compose up -d

    2. Then you can run these tests: pytest -m integration

Note:
    These are INTEGRATION tests, not unit tests. They require MySQL running.
    Mark them with @mark.integration and run separately from unit tests.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC
from time import time
from uuid import uuid4

import asyncmy
from pytest import fixture, main, mark

from async_task.drivers.mysql_driver import MySQLDriver

# Test configuration
MYSQL_DSN = "mysql://test:test@localhost:3306/test_db"
TEST_QUEUE_TABLE = f"test_queue_{uuid4().hex[:8]}"
TEST_DLQ_TABLE = f"test_dlq_{uuid4().hex[:8]}"


@fixture(scope="session")
def mysql_dsn() -> str:
    """
    MySQL connection DSN.

    Override this fixture in conftest.py if using custom MySQL configuration.
    """
    return MYSQL_DSN


@fixture
async def mysql_conn(mysql_dsn: str) -> AsyncGenerator[asyncmy.Connection, None]:
    """
    Create a MySQL connection for direct database operations.
    """
    # Parse DSN: mysql://user:pass@host:port/dbname
    dsn_parts = mysql_dsn.replace("mysql://", "").split("@")
    user_pass = dsn_parts[0].split(":")
    host_port_db = dsn_parts[1].split("/")
    host_port = host_port_db[0].split(":")

    conn = await asyncmy.connect(
        host=host_port[0] if len(host_port) > 0 else "localhost",
        port=int(host_port[1]) if len(host_port) > 1 else 3306,
        user=user_pass[0] if len(user_pass) > 0 else "test",
        password=user_pass[1] if len(user_pass) > 1 else "test",
        db=host_port_db[1] if len(host_port_db) > 1 else "test_db",
        autocommit=True,  # Enable autocommit to prevent metadata lock issues
    )
    yield conn
    await conn.ensure_closed()


@fixture
async def mysql_driver(mysql_dsn: str) -> AsyncGenerator[MySQLDriver, None]:
    """
    Create a MySQLDriver instance configured for testing.
    """
    driver = MySQLDriver(
        dsn=mysql_dsn,
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
    # Use a separate connection (outside pool) with autocommit for DROP TABLE
    # This avoids metadata lock issues from pool connections that may still hold locks
    await driver.disconnect()  # Close pool first to release all connections

    # Now use a fresh connection with autocommit for DROP TABLE
    dsn_parts = mysql_dsn.replace("mysql://", "").split("@")
    user_pass = dsn_parts[0].split(":")
    host_port_db = dsn_parts[1].split("/")
    host_port = host_port_db[0].split(":")

    drop_conn = await asyncmy.connect(
        host=host_port[0] if len(host_port) > 0 else "localhost",
        port=int(host_port[1]) if len(host_port) > 1 else 3306,
        user=user_pass[0] if len(user_pass) > 0 else "test",
        password=user_pass[1] if len(user_pass) > 1 else "test",
        db=host_port_db[1] if len(host_port_db) > 1 else "test_db",
        autocommit=True,  # Critical: autocommit prevents metadata lock issues
    )
    try:
        async with drop_conn.cursor() as cursor:
            await cursor.execute(f"DROP TABLE IF EXISTS {TEST_QUEUE_TABLE}")
            await cursor.execute(f"DROP TABLE IF EXISTS {TEST_DLQ_TABLE}")
    finally:
        await drop_conn.ensure_closed()


@fixture(autouse=True)
async def clean_queue(mysql_driver: MySQLDriver) -> AsyncGenerator[None, None]:
    """
    Fixture that ensures tables are clean before and after tests.
    Automatically applied to all tests in this module.
    """
    # Clear tables before test
    if mysql_driver.pool:
        async with mysql_driver.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"DELETE FROM {TEST_QUEUE_TABLE}")
                await cursor.execute(f"DELETE FROM {TEST_DLQ_TABLE}")

    yield

    # Clear tables after test
    if mysql_driver.pool:
        async with mysql_driver.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"DELETE FROM {TEST_QUEUE_TABLE}")
                await cursor.execute(f"DELETE FROM {TEST_DLQ_TABLE}")


@mark.integration
class TestMySQLDriverWithRealMySQL:
    """Integration tests for MySQLDriver using real MySQL.

    Tests validate transactional dequeue using SELECT FOR UPDATE SKIP LOCKED,
    visibility timeout, dead-letter queue, and retry logic.
    """

    async def test_driver_initialization(self, mysql_driver: MySQLDriver) -> None:
        """Test that driver initializes correctly with real MySQL."""
        assert mysql_driver.pool is not None
        assert mysql_driver.dsn == MYSQL_DSN
        assert mysql_driver.queue_table == TEST_QUEUE_TABLE
        assert mysql_driver.dead_letter_table == TEST_DLQ_TABLE

        # Verify connection works
        async with mysql_driver.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                assert result[0] == 1

    async def test_init_schema_creates_tables(
        self, mysql_dsn: str, mysql_conn: asyncmy.Connection
    ) -> None:
        """Test that init_schema creates queue and dead-letter tables."""
        # Arrange
        queue_table = f"test_schema_queue_{uuid4().hex[:8]}"
        dlq_table = f"test_schema_dlq_{uuid4().hex[:8]}"
        driver = MySQLDriver(
            dsn=mysql_dsn,
            queue_table=queue_table,
            dead_letter_table=dlq_table,
        )

        try:
            # Act
            await driver.init_schema()

            # Assert - check tables exist
            async with mysql_conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = %s
                    """,
                    (queue_table,),
                )
                queue_exists = (await cursor.fetchone())[0] > 0

                await cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = %s
                    """,
                    (dlq_table,),
                )
                dlq_exists = (await cursor.fetchone())[0] > 0

                assert queue_exists is True
                assert dlq_exists is True

                # Check index exists
                await cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.statistics
                    WHERE table_schema = DATABASE() AND index_name = %s
                    """,
                    (f"idx_{queue_table}_lookup",),
                )
                index_exists = (await cursor.fetchone())[0] > 0
                assert index_exists is True

        finally:
            # Cleanup
            if driver.pool:
                async with driver.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(f"DROP TABLE IF EXISTS {queue_table}")
                        await cursor.execute(f"DROP TABLE IF EXISTS {dlq_table}")
            await driver.disconnect()

    async def test_init_schema_is_idempotent(self, mysql_driver: MySQLDriver) -> None:
        """Test that init_schema can be called multiple times safely."""
        # Act & Assert - should not raise
        await mysql_driver.init_schema()
        await mysql_driver.init_schema()
        await mysql_driver.init_schema()

    async def test_enqueue_and_dequeue_single_task(self, mysql_driver: MySQLDriver) -> None:
        """Test enqueuing and dequeuing a single task."""
        # Arrange
        task_data = b"test_task_data"

        # Act - Enqueue
        await mysql_driver.enqueue("default", task_data)

        # Act - Dequeue
        receipt_handle = await mysql_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt_handle is not None
        assert isinstance(receipt_handle, bytes)
        assert len(receipt_handle) == 16  # UUID bytes

    async def test_enqueue_immediate_task(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """Immediate task (delay=0) should be added to database with available_at <= NOW()."""
        # Arrange
        task_data = b"immediate_task"

        # Act
        await mysql_driver.enqueue("default", task_data, delay_seconds=0)

        # Assert
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TEST_QUEUE_TABLE} WHERE queue_name = %s", ("default",)
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[2] == task_data  # payload is at index 2
            assert result[5] == "pending"  # status is at index 5
            assert result[6] == 0  # attempts is at index 6

    async def test_enqueue_multiple_tasks_preserves_fifo_order(
        self, mysql_driver: MySQLDriver
    ) -> None:
        """Tasks should be dequeued in FIFO order (ordered by created_at)."""
        assert mysql_driver.pool is not None
        # Arrange
        tasks = [b"task1", b"task2", b"task3"]

        # Act
        for task in tasks:
            await mysql_driver.enqueue("default", task)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Assert - dequeue in same order
        for expected_task in tasks:
            receipt = await mysql_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None

            # Verify task data via database
            task_id = mysql_driver._receipt_handles.get(receipt)
            assert task_id is not None
            async with mysql_driver.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT payload FROM {TEST_QUEUE_TABLE} WHERE id = %s", (task_id,)
                    )
                    result = await cursor.fetchone()
                    assert result is not None
                    assert result[0] == expected_task

            # Ack to clean up
            await mysql_driver.ack("default", receipt)

    async def test_enqueue_delayed_task(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """Delayed task should be added with available_at in the future."""
        # Arrange
        task_data = b"delayed_task"
        delay_seconds = 5
        before_time = time()

        # Act
        await mysql_driver.enqueue("default", task_data, delay_seconds=delay_seconds)

        # Assert
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT available_at FROM {TEST_QUEUE_TABLE} WHERE queue_name = %s", ("default",)
            )
            result = await cursor.fetchone()
            assert result is not None

            # Calculate expected time
            # MySQL DATETIME is timezone-naive, so we need to treat it as UTC
            available_at_dt = result[0]
            if available_at_dt.tzinfo is None:
                # Make it UTC-aware if it's naive
                available_at_dt = available_at_dt.replace(tzinfo=UTC)
            available_at = available_at_dt.timestamp()
            expected_time = before_time + delay_seconds
            assert abs(available_at - expected_time) < 2.0  # Within 2 seconds tolerance

    async def test_dequeue_returns_receipt_handle(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """dequeue() should return receipt handle (UUID bytes)."""
        # Arrange
        task_data = b"test_task"
        await mysql_driver.enqueue("default", task_data)

        # Act
        receipt = await mysql_driver.dequeue("default", poll_seconds=0)

        # Assert
        assert receipt is not None
        assert isinstance(receipt, bytes)
        assert len(receipt) == 16  # UUID is 16 bytes

    async def test_dequeue_sets_status_to_processing(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """dequeue() should set task status to 'processing' and set locked_until."""
        # Arrange
        await mysql_driver.enqueue("default", b"task")

        # Act
        receipt = await mysql_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Assert
        task_id = mysql_driver._receipt_handles[receipt]
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT status, locked_until FROM {TEST_QUEUE_TABLE} WHERE id = %s", (task_id,)
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "processing"
            assert result[1] is not None

            # locked_until should be in the future
            # MySQL DATETIME is timezone-naive, so we need to treat it as UTC
            locked_until_dt = result[1]
            if locked_until_dt.tzinfo is None:
                # Make it UTC-aware if it's naive
                locked_until_dt = locked_until_dt.replace(tzinfo=UTC)
            locked_until = locked_until_dt.timestamp()
            assert locked_until > time()

    async def test_dequeue_empty_queue_returns_none(self, mysql_driver: MySQLDriver) -> None:
        """dequeue() should return None for empty queue with poll_seconds=0."""
        # Act
        result = await mysql_driver.dequeue("empty_queue", poll_seconds=0)

        # Assert
        assert result is None

    async def test_dequeue_with_poll_waits(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """dequeue() with poll_seconds should wait for tasks."""

        # Arrange
        async def enqueue_delayed():
            await asyncio.sleep(0.3)
            await mysql_driver.enqueue("default", b"delayed")

        # Act
        enqueue_task = asyncio.create_task(enqueue_delayed())
        result = await mysql_driver.dequeue("default", poll_seconds=2)

        # Assert
        assert result is not None

        # Cleanup
        await enqueue_task

    async def test_dequeue_poll_expires(self, mysql_driver: MySQLDriver) -> None:
        """dequeue() should return None when poll duration expires."""
        # Act
        start = time()
        result = await mysql_driver.dequeue("empty", poll_seconds=1)
        elapsed = time() - start

        # Assert
        assert result is None
        assert elapsed >= 0.9  # Account for some timing variance

    async def test_ack_removes_task(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """ack() removes task from database."""
        # Arrange
        await mysql_driver.enqueue("default", b"task")
        receipt = await mysql_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await mysql_driver.ack("default", receipt)

        # Assert - task should not exist in database
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE}")
            count = (await cursor.fetchone())[0]
            assert count == 0

        # Receipt handle should be cleared
        assert receipt not in mysql_driver._receipt_handles

    async def test_nack_requeues_task(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """nack() should requeue task with incremented attempts."""
        # Arrange
        task_data = b"failed_task"
        await mysql_driver.enqueue("default", task_data)
        receipt = await mysql_driver.dequeue("default", poll_seconds=0)
        assert receipt is not None

        # Act
        await mysql_driver.nack("default", receipt)

        # Assert - task should be requeued with attempts=1
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT attempts, status FROM {TEST_QUEUE_TABLE} WHERE queue_name = %s",
                ("default",),
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == 1
            assert result[1] == "pending"

        # Receipt handle should be cleared
        assert receipt not in mysql_driver._receipt_handles

    async def test_nack_moves_to_dead_letter_after_max_attempts(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """nack() should move task to dead letter queue after max_attempts."""
        # Arrange
        task_data = b"failing_task"
        await mysql_driver.enqueue("default", task_data)

        # Act - nack max_attempts times
        for attempt in range(mysql_driver.max_attempts):
            receipt = await mysql_driver.dequeue("default", poll_seconds=0)
            assert receipt is not None
            await mysql_driver.nack("default", receipt)

            # Make task available again for next iteration (except last one which goes to DLQ)
            if attempt < mysql_driver.max_attempts - 1:
                async with mysql_conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE {TEST_QUEUE_TABLE} SET available_at = DATE_SUB(NOW(6), INTERVAL 1 SECOND), locked_until = NULL WHERE queue_name = %s",
                        ("default",),
                    )
                # With autocommit=True, the update is already committed

        # Assert - task should be in dead letter queue
        async with mysql_conn.cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TEST_DLQ_TABLE} WHERE queue_name = %s", ("default",)
            )
            dlq_result = await cursor.fetchone()
            assert dlq_result is not None
            assert dlq_result[2] == task_data  # payload
            assert dlq_result[3] == mysql_driver.max_attempts  # attempts
            assert dlq_result[4] == "Max retries exceeded"  # error_message

            # Task should not be in main queue
            await cursor.execute(
                f"SELECT COUNT(*) FROM {TEST_QUEUE_TABLE} WHERE queue_name = %s", ("default",)
            )
            queue_count = (await cursor.fetchone())[0]
            assert queue_count == 0

    async def test_get_queue_size_returns_count(
        self, mysql_driver: MySQLDriver, mysql_conn: asyncmy.Connection
    ) -> None:
        """get_queue_size() should return number of ready tasks."""
        # Arrange
        for i in range(3):
            await mysql_driver.enqueue("default", f"task{i}".encode())

        # Act
        size = await mysql_driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 3

    async def test_get_queue_size_empty_queue(self, mysql_driver: MySQLDriver) -> None:
        """get_queue_size() should return 0 for empty queue."""
        # Act
        size = await mysql_driver.get_queue_size(
            "empty", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 0


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
