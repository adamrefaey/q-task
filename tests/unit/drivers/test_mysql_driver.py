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

from async_task.drivers.mysql_driver import MySQLDriver


@mark.unit
class TestMySQLDriverErrorHandling:
    """Test MySQLDriver error handling and rollback scenarios."""

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
