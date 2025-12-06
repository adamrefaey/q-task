"""Unit tests for RedisDriver.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Use mocks to test RedisDriver without requiring real Redis
- Test all methods, edge cases, and error conditions
- Achieve >90% code coverage
"""

from inspect import isawaitable
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark

from asynctasq.drivers.redis_driver import RedisDriver, maybe_await


@mark.unit
class TestMaybeAwait:
    """Test maybe_await helper function."""

    @mark.asyncio
    async def test_maybe_await_with_awaitable(self) -> None:
        """Test maybe_await with an awaitable object."""

        # Arrange
        async def async_func() -> str:
            return "result"

        result = async_func()

        # Act
        value = await maybe_await(result)

        # Assert
        assert value == "result"
        assert isawaitable(result)  # Original is still awaitable

    @mark.asyncio
    async def test_maybe_await_with_non_awaitable(self) -> None:
        """Test maybe_await with a non-awaitable object."""
        # Arrange
        non_awaitable = "not awaitable"

        # Act
        value = await maybe_await(non_awaitable)

        # Assert
        assert value == "not awaitable"

    @mark.asyncio
    async def test_maybe_await_with_coroutine(self) -> None:
        """Test maybe_await with a coroutine."""

        # Arrange
        async def coro() -> int:
            return 42

        coro_obj = coro()

        # Act
        value = await maybe_await(coro_obj)

        # Assert
        assert value == 42

    @mark.asyncio
    async def test_maybe_await_with_none(self) -> None:
        """Test maybe_await with None."""
        # Act
        value = await maybe_await(None)

        # Assert
        assert value is None


@mark.unit
class TestRedisDriverInitialization:
    """Test RedisDriver initialization and connection lifecycle."""

    def test_driver_initializes_with_defaults(self) -> None:
        """Test driver initializes with default values."""
        # Act
        driver = RedisDriver()

        # Assert
        assert driver.url == "redis://localhost:6379"
        assert driver.password is None
        assert driver.db == 0
        assert driver.max_connections == 10
        assert driver.client is None

    def test_driver_initializes_with_custom_values(self) -> None:
        """Test driver initializes with custom values."""
        # Act
        driver = RedisDriver(
            url="redis://custom:6379",
            password="secret",
            db=5,
            max_connections=20,
        )

        # Assert
        assert driver.url == "redis://custom:6379"
        assert driver.password == "secret"
        assert driver.db == 5
        assert driver.max_connections == 20
        assert driver.client is None

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_connect_creates_redis_client(self, mock_redis_class: MagicMock) -> None:
        """Test connect creates Redis client with correct parameters."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver(url="redis://test:6379", password="pass", db=2, max_connections=15)

        # Act
        await driver.connect()

        # Assert
        mock_redis_class.from_url.assert_called_once_with(
            "redis://test:6379",
            password="pass",
            db=2,
            decode_responses=False,
            max_connections=15,
            protocol=3,
        )
        assert driver.client == mock_client

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_connect_is_idempotent(self, mock_redis_class: MagicMock) -> None:
        """Test multiple connect calls are safe."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()

        # Act
        await driver.connect()
        first_client = driver.client
        await driver.connect()  # Second call
        second_client = driver.client

        # Assert
        assert first_client is second_client
        mock_redis_class.from_url.assert_called_once()  # Only called once

    @mark.asyncio
    async def test_disconnect_closes_client(self) -> None:
        """Test disconnect closes Redis client."""
        # Arrange
        mock_client = AsyncMock()
        driver = RedisDriver()
        driver.client = mock_client

        # Act
        await driver.disconnect()

        # Assert
        mock_client.aclose.assert_called_once()
        assert driver.client is None

    @mark.asyncio
    async def test_disconnect_is_idempotent(self) -> None:
        """Test multiple disconnect calls are safe."""
        # Arrange
        mock_client = AsyncMock()
        driver = RedisDriver()
        driver.client = mock_client

        # Act
        await driver.disconnect()
        await driver.disconnect()  # Second call

        # Assert
        assert driver.client is None
        mock_client.aclose.assert_called_once()  # Only called once

    @mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        """Test disconnect when client is None is safe."""
        # Arrange
        driver = RedisDriver()
        driver.client = None

        # Act & Assert - should not raise
        await driver.disconnect()
        assert driver.client is None


@mark.unit
class TestRedisDriverEnqueue:
    """Test task enqueueing functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_enqueue_immediate_task(self, mock_redis_class: MagicMock) -> None:
        """Test enqueue immediate task (delay=0) uses LPUSH."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lpush = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.enqueue("default", b"task_data", delay_seconds=0)

        # Assert
        mock_client.lpush.assert_called_once_with("queue:default", b"task_data")

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_enqueue_delayed_task(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test enqueue delayed task uses ZADD."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.zadd = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.enqueue("default", b"delayed_task", delay_seconds=5)

        # Assert
        mock_client.zadd.assert_called_once_with("queue:default:delayed", {b"delayed_task": 1005.0})

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_enqueue_auto_connects(self, mock_redis_class: MagicMock) -> None:
        """Test enqueue automatically connects if not connected."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lpush = AsyncMock(return_value=1)
        driver = RedisDriver()

        # Act
        await driver.enqueue("default", b"task_data")

        # Assert
        mock_redis_class.from_url.assert_called_once()
        mock_client.lpush.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_enqueue_handles_awaitable_result(self, mock_redis_class: MagicMock) -> None:
        """Test enqueue handles awaitable Redis results."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client

        # Make lpush return a coroutine
        async def lpush_coro(*args: object, **kwargs: object) -> int:
            return 1

        mock_client.lpush = lpush_coro
        driver = RedisDriver()
        await driver.connect()

        # Act & Assert - should not raise
        await driver.enqueue("default", b"task_data")


@mark.unit
class TestRedisDriverDequeue:
    """Test task dequeuing functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_dequeue_uses_lmove(self, mock_redis_class: MagicMock) -> None:
        """Test dequeue uses LMOVE to move task to processing."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lmove = AsyncMock(return_value=b"task_data")
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()
        await driver.connect()

        # Act
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        mock_client.lmove.assert_called_once_with(
            "queue:default", "queue:default:processing", "RIGHT", "LEFT"
        )
        assert result == b"task_data"

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_dequeue_uses_blmove_with_poll(self, mock_redis_class: MagicMock) -> None:
        """Test dequeue uses BLMOVE when poll_seconds > 0."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.blmove = AsyncMock(return_value=b"task_data")
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()
        await driver.connect()

        # Act
        result = await driver.dequeue("default", poll_seconds=5)

        # Assert
        mock_client.blmove.assert_called_once_with(
            "queue:default", "queue:default:processing", 5, "RIGHT", "LEFT"
        )
        assert result == b"task_data"

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_dequeue_returns_none_when_empty(self, mock_redis_class: MagicMock) -> None:
        """Test dequeue returns None when queue is empty."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lmove = AsyncMock(return_value=None)
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()
        await driver.connect()

        # Act
        result = await driver.dequeue("default", poll_seconds=0)

        # Assert
        assert result is None

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_dequeue_auto_connects(self, mock_redis_class: MagicMock) -> None:
        """Test dequeue automatically connects if not connected."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lmove = AsyncMock(return_value=None)
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        mock_redis_class.from_url.assert_called_once()
        mock_client.lmove.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_dequeue_processes_delayed_tasks(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test dequeue processes ready delayed tasks."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        ready_tasks = [b"task1", b"task2"]
        mock_client.zrangebyscore = AsyncMock(return_value=ready_tasks)
        mock_client.lmove = AsyncMock(return_value=None)

        # Mock pipeline as async context manager
        # When used as `async with client.pipeline() as pipe:`, __aenter__ returns the pipe
        # Pipeline methods (lpush, zremrangebyscore) are synchronous, execute is async
        mock_pipe = MagicMock()
        mock_pipe.lpush = MagicMock(
            return_value=mock_pipe
        )  # Pipeline methods return self for chaining
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock()
        # Make pipeline return an async context manager
        mock_client.pipeline = MagicMock(return_value=mock_pipe)
        # Configure __aenter__ to return the pipe itself
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        mock_client.zrangebyscore.assert_called_once_with(
            "queue:default:delayed", min="-inf", max=1000.0
        )
        mock_client.pipeline.assert_called_once_with(transaction=True)
        mock_pipe.lpush.assert_called_once_with("queue:default", *ready_tasks)
        mock_pipe.zremrangebyscore.assert_called_once_with("queue:default:delayed", 0, 1000.0)
        mock_pipe.execute.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_dequeue_skips_not_ready_delayed_tasks(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test dequeue skips delayed tasks that aren't ready."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.zrangebyscore = AsyncMock(return_value=[])  # No ready tasks
        mock_client.lmove = AsyncMock(return_value=None)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        mock_client.zrangebyscore.assert_called_once()
        # Pipeline should not be used when no ready tasks
        mock_client.pipeline.assert_not_called()


@mark.unit
class TestRedisDriverAck:
    """Test task acknowledgment functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_ack_removes_from_processing(self, mock_redis_class: MagicMock) -> None:
        """Test ack removes task from processing list."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lrem = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.ack("default", b"task_data")

        # Assert
        mock_client.lrem.assert_called_once_with("queue:default:processing", 1, b"task_data")

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_ack_auto_connects(self, mock_redis_class: MagicMock) -> None:
        """Test ack automatically connects if not connected."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lrem = AsyncMock(return_value=1)
        driver = RedisDriver()

        # Act
        await driver.ack("default", b"task_data")

        # Assert
        mock_redis_class.from_url.assert_called_once()
        mock_client.lrem.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_ack_handles_awaitable_result(self, mock_redis_class: MagicMock) -> None:
        """Test ack handles awaitable Redis results."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client

        # Make lrem return a coroutine
        async def lrem_coro(*args: object, **kwargs: object) -> int:
            return 1

        mock_client.lrem = lrem_coro
        driver = RedisDriver()
        await driver.connect()

        # Act & Assert - should not raise
        await driver.ack("default", b"task_data")


@mark.unit
class TestRedisDriverNack:
    """Test task rejection/retry functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_nack_requeues_task(self, mock_redis_class: MagicMock) -> None:
        """Test nack requeues task if it exists in processing."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lrem = AsyncMock(return_value=1)  # Task found and removed
        mock_client.lpush = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.nack("default", b"task_data")

        # Assert
        mock_client.lrem.assert_called_once_with("queue:default:processing", 1, b"task_data")
        mock_client.lpush.assert_called_once_with("queue:default", b"task_data")

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_nack_does_not_requeue_if_not_in_processing(
        self, mock_redis_class: MagicMock
    ) -> None:
        """Test nack does not requeue if task not in processing (nack-after-ack protection)."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lrem = AsyncMock(return_value=0)  # Task not found
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.nack("default", b"task_data")

        # Assert
        mock_client.lrem.assert_called_once()
        mock_client.lpush.assert_not_called()  # Should not requeue

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_nack_auto_connects(self, mock_redis_class: MagicMock) -> None:
        """Test nack automatically connects if not connected."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lrem = AsyncMock(return_value=0)
        driver = RedisDriver()

        # Act
        await driver.nack("default", b"task_data")

        # Assert
        mock_redis_class.from_url.assert_called_once()
        mock_client.lrem.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_nack_handles_awaitable_result(self, mock_redis_class: MagicMock) -> None:
        """Test nack handles awaitable Redis results."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client

        # Make lrem return a coroutine
        async def lrem_coro(*args: object, **kwargs: object) -> int:
            return 1

        mock_client.lrem = lrem_coro
        mock_client.lpush = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act & Assert - should not raise
        await driver.nack("default", b"task_data")


@mark.unit
class TestRedisDriverGetQueueSize:
    """Test queue size reporting functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_returns_main_queue_size(
        self, mock_redis_class: MagicMock
    ) -> None:
        """Test get_queue_size returns main queue size."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(return_value=5)
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        mock_client.llen.assert_called_once_with("queue:default")
        assert size == 5

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_includes_delayed(self, mock_redis_class: MagicMock) -> None:
        """Test get_queue_size includes delayed tasks when requested."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(return_value=3)
        mock_client.zcard = AsyncMock(return_value=2)
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size("default", include_delayed=True, include_in_flight=False)

        # Assert
        mock_client.llen.assert_called_once_with("queue:default")
        mock_client.zcard.assert_called_once_with("queue:default:delayed")
        assert size == 5  # 3 + 2

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_includes_in_flight(self, mock_redis_class: MagicMock) -> None:
        """Test get_queue_size includes in-flight tasks when requested."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(side_effect=[3, 1])  # main queue, processing
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size("default", include_delayed=False, include_in_flight=True)

        # Assert
        assert mock_client.llen.call_count == 2
        assert size == 4  # 3 + 1

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_includes_all(self, mock_redis_class: MagicMock) -> None:
        """Test get_queue_size includes all when both flags are True."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(side_effect=[3, 2])  # main queue, processing
        mock_client.zcard = AsyncMock(return_value=1)  # delayed
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size("default", include_delayed=True, include_in_flight=True)

        # Assert
        assert size == 6  # 3 + 1 + 2

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_auto_connects(self, mock_redis_class: MagicMock) -> None:
        """Test get_queue_size automatically connects if not connected."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(return_value=0)
        driver = RedisDriver()

        # Act
        await driver.get_queue_size("default", include_delayed=False, include_in_flight=False)

        # Assert
        mock_redis_class.from_url.assert_called_once()
        mock_client.llen.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_handles_awaitable_result(
        self, mock_redis_class: MagicMock
    ) -> None:
        """Test get_queue_size handles awaitable Redis results."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client

        # Make llen return a coroutine
        async def llen_coro(*args: object, **kwargs: object) -> int:
            return 5

        mock_client.llen = llen_coro
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 5


@mark.unit
class TestRedisDriverProcessDelayedTasks:
    """Test delayed task processing functionality."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_process_delayed_tasks_moves_ready_tasks(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test _process_delayed_tasks moves ready tasks to main queue."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        ready_tasks = [b"task1", b"task2"]
        mock_client.zrangebyscore = AsyncMock(return_value=ready_tasks)

        # Mock pipeline as async context manager
        # When used as `async with client.pipeline() as pipe:`, __aenter__ returns the pipe
        # Pipeline methods (lpush, zremrangebyscore) are synchronous, execute is async
        mock_pipe = MagicMock()
        mock_pipe.lpush = MagicMock(
            return_value=mock_pipe
        )  # Pipeline methods return self for chaining
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock()
        # Make pipeline return an async context manager
        mock_client.pipeline = MagicMock(return_value=mock_pipe)
        # Configure __aenter__ to return the pipe itself
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver._process_delayed_tasks("default")

        # Assert
        mock_client.zrangebyscore.assert_called_once_with(
            "queue:default:delayed", min="-inf", max=1000.0
        )
        mock_client.pipeline.assert_called_once_with(transaction=True)
        mock_pipe.lpush.assert_called_once_with("queue:default", *ready_tasks)
        mock_pipe.zremrangebyscore.assert_called_once_with("queue:default:delayed", 0, 1000.0)
        mock_pipe.execute.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_process_delayed_tasks_no_ready_tasks(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test _process_delayed_tasks does nothing when no ready tasks."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.zrangebyscore = AsyncMock(return_value=[])  # No ready tasks

        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver._process_delayed_tasks("default")

        # Assert
        mock_client.zrangebyscore.assert_called_once()
        mock_client.pipeline.assert_not_called()  # Pipeline not used when no tasks

    @patch("asynctasq.drivers.redis_driver.Redis")
    @patch("asynctasq.drivers.redis_driver.time")
    @mark.asyncio
    async def test_process_delayed_tasks_uses_transaction(
        self, mock_time: MagicMock, mock_redis_class: MagicMock
    ) -> None:
        """Test _process_delayed_tasks uses transaction=True for atomicity."""
        # Arrange
        mock_time.return_value = 1000.0
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.zrangebyscore = AsyncMock(return_value=[b"task1"])

        # Mock pipeline as async context manager
        # When used as `async with client.pipeline() as pipe:`, __aenter__ returns the pipe
        # Pipeline methods (lpush, zremrangebyscore) are synchronous, execute is async
        mock_pipe = MagicMock()
        mock_pipe.lpush = MagicMock(
            return_value=mock_pipe
        )  # Pipeline methods return self for chaining
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock()
        # Make pipeline return an async context manager
        mock_client.pipeline = MagicMock(return_value=mock_pipe)
        # Configure __aenter__ to return the pipe itself
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver._process_delayed_tasks("default")

        # Assert
        mock_client.pipeline.assert_called_once_with(transaction=True)


@mark.unit
class TestRedisDriverEdgeCases:
    """Test edge cases and error conditions."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_enqueue_with_negative_delay(self, mock_redis_class: MagicMock) -> None:
        """Test enqueue with negative delay is treated as immediate."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lpush = AsyncMock(return_value=1)
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.enqueue("default", b"task", delay_seconds=-1)

        # Assert - should use lpush (immediate), not zadd (delayed)
        mock_client.lpush.assert_called_once()
        mock_client.zadd.assert_not_called()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_dequeue_with_zero_poll(self, mock_redis_class: MagicMock) -> None:
        """Test dequeue with poll_seconds=0 uses non-blocking LMOVE."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lmove = AsyncMock(return_value=None)
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.dequeue("default", poll_seconds=0)

        # Assert
        mock_client.lmove.assert_called_once()
        mock_client.blmove.assert_not_called()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_size_empty_queue(self, mock_redis_class: MagicMock) -> None:
        """Test get_queue_size returns 0 for empty queue."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(return_value=0)
        driver = RedisDriver()
        await driver.connect()

        # Act
        size = await driver.get_queue_size(
            "default", include_delayed=False, include_in_flight=False
        )

        # Assert
        assert size == 0

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_operations_with_different_queue_names(self, mock_redis_class: MagicMock) -> None:
        """Test operations work with different queue names."""
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.lpush = AsyncMock(return_value=1)
        mock_client.lmove = AsyncMock(return_value=b"task")
        mock_client.zrangebyscore = AsyncMock(return_value=[])
        driver = RedisDriver()
        await driver.connect()

        # Act
        await driver.enqueue("queue1", b"task1")
        await driver.enqueue("queue2", b"task2")
        result1 = await driver.dequeue("queue1", poll_seconds=0)
        result2 = await driver.dequeue("queue2", poll_seconds=0)

        # Assert
        assert mock_client.lpush.call_count == 2
        assert "queue:queue1" in str(mock_client.lpush.call_args_list[0])
        assert "queue:queue2" in str(mock_client.lpush.call_args_list[1])
        assert result1 == b"task"
        assert result2 == b"task"


@mark.unit
class TestRedisDriverInspectionAndManagement:
    """Unit tests for metadata/management methods added to RedisDriver."""

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_queue_stats_returns_stats(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        mock_client.llen = AsyncMock(side_effect=[4, 2])
        mock_client.get = AsyncMock(side_effect=[b"10", b"3"])
        driver = RedisDriver()
        await driver.connect()

        # Act
        stats = await driver.get_queue_stats("default")

        # Assert
        assert stats.name == "default"
        assert stats.depth == 4
        assert stats.processing == 2
        assert stats.completed_total == 10
        assert stats.failed_total == 3

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_all_queue_names_scans_keys(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        # Simulate scan returning queue keys in two pages
        mock_client.scan = AsyncMock(
            side_effect=[(1, [b"queue:alpha", b"queue:beta:processing"]), (0, [b"other:key"])]
        )
        driver = RedisDriver()
        await driver.connect()

        # Act
        names = await driver.get_all_queue_names()

        # Assert
        assert sorted(names) == ["alpha", "beta"]

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_global_stats_sums_counters(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        # get_all_queue_names will call scan; stub it to return queues
        driver = RedisDriver()
        await driver.connect()
        # Patch get_all_queue_names to return known queues
        driver.get_all_queue_names = AsyncMock(return_value=["q1", "q2"])

        # llen for q1,q2 and processing; get for stats
        async def llen_side(key, *a, **k):
            if key == "queue:q1":
                return 2
            if key == "queue:q1:processing":
                return 1
            if key == "queue:q2":
                return 3
            if key == "queue:q2:processing":
                return 0
            return 0

        async def get_side(key, *a, **k):
            if key == "queue:q1:stats:completed":
                return b"5"
            if key == "queue:q2:stats:failed":
                return b"2"
            return None

        mock_client.llen = AsyncMock(side_effect=llen_side)
        mock_client.get = AsyncMock(side_effect=get_side)

        # Act
        totals = await driver.get_global_stats()

        # Assert
        assert totals["pending"] == 5  # 2 + 3
        assert totals["running"] == 1  # 1 + 0
        assert totals["completed"] == 5
        assert totals["failed"] == 2

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_running_tasks_and_pagination(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        # get_all_queue_names returns one queue
        driver = RedisDriver()
        await driver.connect()
        driver.get_all_queue_names = AsyncMock(return_value=["default"])
        # processing list contains two items
        mock_client.lrange = AsyncMock(return_value=[b"id-1234567890abcdef-task", b"short"])

        # Act
        running = await driver.get_running_tasks(limit=1, offset=0)

        # Assert - pagination limits returned items
        assert isinstance(running, list)
        assert len(running) == 1
        # Now returns (bytes, str) tuples
        assert running[0][1] == "default"

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_tasks_filters_and_counts(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()
        await driver.connect()
        driver.get_all_queue_names = AsyncMock(return_value=["default"])

        # pending has one, processing has one
        async def lrange_side(key, *a, **k):
            if key == "queue:default":
                return [b"pending_task_abcdefghij1234567890"]
            if key == "queue:default:processing":
                return [b"processing_task_abcdefghij1234567890"]
            return []

        mock_client.lrange = AsyncMock(side_effect=lrange_side)

        # Act - no status filter (both)
        results, total = await driver.get_tasks()

        # Assert
        assert total == 2
        assert len(results) == 2

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_task_by_id_finds_match(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()
        await driver.connect()
        driver.get_all_queue_names = AsyncMock(return_value=["q"])
        # Create a properly msgpack-serialized task
        import msgpack

        task_id = "t" * 36
        task_data = {"task_id": task_id, "task_name": "test_task"}
        raw = msgpack.packb(task_data)
        mock_client.lrange = AsyncMock(return_value=[raw])

        # Act
        ti = await driver.get_task_by_id(task_id)

        # Assert - now returns raw msgpack bytes
        assert ti is not None
        assert ti == raw

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_retry_task_moves_from_dead(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()
        await driver.connect()
        driver.get_all_queue_names = AsyncMock(return_value=["q"])
        # dead list contains a raw that starts with task id
        task_id = "retry-id-1"
        raw = (task_id + ":payload").encode()
        mock_client.lrange = AsyncMock(return_value=[raw])
        mock_client.lrem = AsyncMock(return_value=1)
        mock_client.rpush = AsyncMock(return_value=1)

        # Act
        ok = await driver.retry_task(task_id)

        # Assert
        assert ok is True
        mock_client.lrem.assert_called_once()
        mock_client.rpush.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_delete_task_removes_matching(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()
        await driver.connect()
        driver.get_all_queue_names = AsyncMock(return_value=["q"])
        task_id = "delme-1"
        raw = (task_id + ":foo").encode()

        # lrange for '' returns the item
        async def lrange_side(key, *a, **k):
            if key.endswith(":dead"):
                return [raw]
            return []

        mock_client.lrange = AsyncMock(side_effect=lrange_side)
        mock_client.lrem = AsyncMock(return_value=1)

        # Act
        removed = await driver.delete_task(task_id)

        # Assert
        assert removed is True
        mock_client.lrem.assert_called_once()

    @patch("asynctasq.drivers.redis_driver.Redis")
    @mark.asyncio
    async def test_get_worker_stats_parses_hashes(self, mock_redis_class: MagicMock) -> None:
        # Arrange
        mock_client = AsyncMock()
        mock_redis_class.from_url.return_value = mock_client
        driver = RedisDriver()
        await driver.connect()
        # Simulate scan returning one worker key
        mock_client.scan = AsyncMock(side_effect=[(0, [b"worker:abc"])])
        # hgetall returns bytes keys/values
        mock_client.hgetall = AsyncMock(
            return_value={
                b"status": b"busy",
                b"tasks_processed": b"7",
                b"uptime_seconds": b"100",
                b"last_heartbeat": b"0",
            }
        )

        # Act
        workers = await driver.get_worker_stats()

        # Assert
        assert isinstance(workers, list)
        assert len(workers) == 1
        w = workers[0]
        assert w.worker_id == "abc"
        assert w.status == "busy"


if __name__ == "__main__":
    from pytest import main

    main([__file__, "-s", "-m", "unit"])
