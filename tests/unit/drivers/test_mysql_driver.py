"""Unit tests for MySQLDriver.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Use mocks to test MySQLDriver without requiring real MySQL
- Test error handling paths and rollback scenarios
- Achieve 100% code coverage when combined with integration tests
"""

from unittest.mock import AsyncMock, MagicMock

from pytest import mark, raises

from asynctasq.drivers.mysql_driver import MySQLDriver


@mark.unit
class TestMySQLDriverErrorHandling:
    """Test MySQLDriver error handling and rollback scenarios."""

    @mark.asyncio
    async def test_enqueue_rollback_on_exception(self) -> None:
        """Test that enqueue() rolls back transaction on exception."""
        # Arrange
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Setup async context manager for pool.acquire()
        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # Setup async context manager for conn.cursor()
        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        driver.pool = mock_pool
        mock_cursor.execute.side_effect = Exception("Database error")

        # Act & Assert
        with raises(Exception, match="Database error"):
            await driver.enqueue("test_queue", b"task_data", delay_seconds=0)

        # Assert - rollback was called
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    @mark.asyncio
    async def test_dequeue_rollback_on_exception(self) -> None:
        """Test that dequeue() rolls back transaction on exception."""
        # Arrange
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Setup async context manager for pool.acquire()
        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # Setup async context manager for conn.cursor()
        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        driver.pool = mock_pool
        mock_cursor.execute.side_effect = Exception("Database error")

        # Act & Assert
        with raises(Exception, match="Database error"):
            await driver.dequeue("test_queue", poll_seconds=0)

        # Assert - rollback was called
        mock_conn.rollback.assert_called_once()

    @mark.asyncio
    async def test_dequeue_rollback_when_no_task_found(self) -> None:
        """Test that dequeue() rolls back when no task is found."""
        # Arrange
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Setup async context manager for pool.acquire()
        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # Setup async context manager for conn.cursor()
        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        driver.pool = mock_pool
        mock_cursor.fetchone.return_value = None  # No task found

        # Act
        result = await driver.dequeue("test_queue", poll_seconds=0)

        # Assert
        assert result is None
        mock_conn.rollback.assert_called_once()

    @mark.asyncio
    async def test_ack_rollback_on_exception(self) -> None:
        """Test that ack() rolls back transaction on exception."""
        # Arrange
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        driver._receipt_handles = {b"receipt_handle": 123}

        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Setup async context manager for pool.acquire()
        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # Setup async context manager for conn.cursor()
        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        driver.pool = mock_pool
        mock_cursor.execute.side_effect = Exception("Database error")

        # Act & Assert
        with raises(Exception, match="Database error"):
            await driver.ack("test_queue", b"receipt_handle")

        # Assert - rollback was called
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    @mark.asyncio
    async def test_nack_rollback_on_exception(self) -> None:
        """Test that nack() rolls back transaction on exception."""
        # Arrange
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        driver._receipt_handles = {b"receipt_handle": 123}

        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Setup async context manager for pool.acquire()
        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # Setup async context manager for conn.cursor()
        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        driver.pool = mock_pool

        # First execute (SELECT) succeeds, fetchone returns data, second execute (UPDATE) fails
        mock_cursor.fetchone.return_value = (
            0,
            3,
            "test_queue",
            b"payload",
        )  # attempts, max_attempts, queue_name, payload

        # Use side_effect to make first execute succeed, second fail
        execute_call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal execute_call_count
            execute_call_count += 1
            if execute_call_count == 1:
                return None  # SELECT succeeds
            else:
                raise Exception("Database error")  # UPDATE fails

        mock_cursor.execute.side_effect = execute_side_effect

        # Act & Assert
        with raises(Exception, match="Database error"):
            await driver.nack("test_queue", b"receipt_handle")

        # Assert - rollback was called
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    # Note: Line 279 in dequeue() is defensive code that's unreachable in normal execution.
    # If poll_seconds > 0, deadline is always set. The else branch at line 279 is defensive
    # code that would require complex bytecode manipulation to test, which isn't practical.
    # This line can be marked with `# pragma: no cover` if desired, or we accept ~99.5% coverage.


@mark.unit
class TestMySQLDriverStatsAndManagement:
    @mark.asyncio
    async def test_get_queue_stats_and_global(self) -> None:
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        # Setup fetchone return values for sequence of calls
        # get_queue_stats: depth, processing, failed
        # get_global_stats: pending, processing, failed, total
        mock_cursor.fetchone.side_effect = [(5,), (2,), (1,), (10,), (3,), (1,), (20,)]

        driver.pool = mock_pool

        qs = await driver.get_queue_stats("default")
        assert qs.name == "default"
        assert qs.depth == 5
        assert qs.processing == 2

        g = await driver.get_global_stats()
        assert g["pending"] == 10
        assert g["running"] == 3
        assert g["failed"] == 1
        assert g["total"] == 20

    @mark.asyncio
    async def test_get_all_queue_names_and_running_tasks(self) -> None:
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        # fetchall for queue names
        mock_cursor.fetchall.side_effect = [[("q1",), ("q2",)], [(1, "q1", 1, 3, None, None)]]

        driver.pool = mock_pool
        names = await driver.get_all_queue_names()
        assert names == ["q1", "q2"]

        running = await driver.get_running_tasks(limit=1, offset=0)
        assert isinstance(running, list)
        assert len(running) == 1

    @mark.asyncio
    async def test_get_tasks_and_get_task_by_id(self) -> None:
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        # rows for get_tasks (now returns payload, queue_name, status)
        mock_cursor.fetchall.side_effect = [
            [(b"task_data", "q", "pending")],
        ]
        mock_cursor.fetchone.side_effect = [(1,), (b"task_by_id_data",)]

        driver.pool = mock_pool
        tasks, total = await driver.get_tasks(status="pending", queue="q", limit=1, offset=0)
        assert total == 1
        assert len(tasks) == 1
        # Now returns list of (bytes, queue_name, status) tuples
        assert tasks[0] == (b"task_data", "q", "pending")

        # get_task_by_id (now returns just payload bytes)
        t = await driver.get_task_by_id("1")
        assert t is not None
        assert t == b"task_by_id_data"

    @mark.asyncio
    async def test_retry_and_delete_task(self) -> None:
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        mock_cursor_context = MagicMock()
        mock_cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_context)

        # retry_task: select returns one row
        mock_cursor.fetchone.side_effect = [
            ("q", b"payload", 1, 3),
        ]
        driver.pool = mock_pool
        mock_conn.begin = AsyncMock()
        mock_conn.commit = AsyncMock()
        mock_conn.rollback = AsyncMock()

        ok = await driver.retry_task("1")
        assert ok is True

        # delete_task: simulate rowcount via attribute on cursor
        def set_rowcount_zero(*a, **k):
            mock_cursor.rowcount = 0

        def set_rowcount_one(*a, **k):
            mock_cursor.rowcount = 1

        # First call: delete from queue returns 1
        mock_cursor.execute.side_effect = set_rowcount_one
        driver.pool = mock_pool
        deleted = await driver.delete_task("1")
        assert deleted is True

        # Second call: delete from queue returns 0, dlq returns 1
        mock_cursor.execute.side_effect = [set_rowcount_zero, set_rowcount_one]
        deleted = await driver.delete_task("2")
        assert deleted is True

    @mark.asyncio
    async def test_get_worker_stats_empty(self) -> None:
        driver = MySQLDriver(dsn="mysql://user:pass@localhost:3306/dbname")
        res = await driver.get_worker_stats()
        assert res == []
