"""Unit tests for RabbitMQDriver.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Use mocks to test RabbitMQDriver without requiring real RabbitMQ
- Test all methods, edge cases, and error conditions
- Achieve >90% code coverage
"""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark

from asynctasq.drivers.rabbitmq_driver import RabbitMQDriver


@mark.unit
class TestRabbitMQDriverInitialization:
    """Test RabbitMQDriver initialization and connection lifecycle."""

    def test_driver_initializes_with_defaults(self) -> None:
        """Test driver initializes with default values."""
        # Act
        driver = RabbitMQDriver()

        # Assert
        assert driver.url == "amqp://guest:guest@localhost:5672/"
        assert driver.exchange_name == "asynctasq"
        assert driver.prefetch_count == 1
        assert driver.connection is None
        assert driver.channel is None

    def test_driver_initializes_with_custom_values(self) -> None:
        """Test driver initializes with custom values."""
        # Act
        driver = RabbitMQDriver(
            url="amqp://user:pass@host:5672/",
            exchange_name="custom_exchange",
            prefetch_count=10,
        )

        # Assert
        assert driver.url == "amqp://user:pass@host:5672/"
        assert driver.exchange_name == "custom_exchange"
        assert driver.prefetch_count == 10

    @mark.asyncio
    async def test_connect_creates_connection_and_channel(self) -> None:
        """Test connect() creates connection and channel."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

            # Act
            await driver.connect()

            # Assert
            assert driver.connection == mock_connection
            assert driver.channel == mock_channel
            assert driver._delayed_exchange == mock_exchange
            mock_connection.channel.assert_called_once()
            mock_channel.set_qos.assert_called_once_with(prefetch_count=1)
            mock_channel.declare_exchange.assert_called_once()

    @mark.asyncio
    async def test_connect_is_idempotent(self) -> None:
        """Test connect() can be called multiple times safely."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

            # Act
            await driver.connect()
            first_connection = driver.connection
            await driver.connect()  # Second call

            # Assert
            assert driver.connection == first_connection
            assert mock_connection.channel.call_count == 1  # Only called once

    @mark.asyncio
    async def test_disconnect_closes_connection_and_channel(self) -> None:
        """Test disconnect() closes connection and channel."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.close = AsyncMock()
            mock_connection.close = AsyncMock()

            await driver.connect()

            # Act
            await driver.disconnect()

            # Assert
            mock_channel.close.assert_called_once()
            mock_connection.close.assert_called_once()
            assert driver.connection is None
            assert driver.channel is None
            assert driver._delayed_exchange is None

    @mark.asyncio
    async def test_disconnect_is_idempotent(self) -> None:
        """Test disconnect() can be called multiple times safely."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.close = AsyncMock()
            mock_connection.close = AsyncMock()

            await driver.connect()

            # Act
            await driver.disconnect()
            await driver.disconnect()  # Second call

            # Assert
            assert mock_channel.close.call_count == 1
            assert mock_connection.close.call_count == 1


@mark.unit
class TestRabbitMQDriverEnqueue:
    """Test RabbitMQDriver.enqueue() method."""

    @mark.asyncio
    async def test_enqueue_immediate_task(self) -> None:
        """Test enqueue() with immediate task (delay=0)."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

            await driver.connect()

            # Act
            await driver.enqueue("default", b"task_data", delay_seconds=0)

            # Assert
            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            assert call_args[1]["routing_key"] == "default"

    @mark.asyncio
    async def test_enqueue_delayed_task(self) -> None:
        """Test enqueue() with delayed task."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_delayed_queue.bind = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)

            await driver.connect()

            # Act
            await driver.enqueue("default", b"task_data", delay_seconds=5)

            # Assert
            mock_channel.declare_queue.assert_called()
            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            assert call_args[1]["routing_key"] == "default_delayed"

    @mark.asyncio
    async def test_enqueue_auto_connects(self) -> None:
        """Test enqueue() auto-connects if not connected."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

            # Act
            await driver.enqueue("default", b"task_data")

            # Assert
            assert driver.connection is not None
            mock_exchange.publish.assert_called_once()


@mark.unit
class TestRabbitMQDriverDequeue:
    """Test RabbitMQDriver.dequeue() method."""

    @mark.asyncio
    async def test_dequeue_returns_task(self) -> None:
        """Test dequeue() returns task data."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_message = AsyncMock()
        mock_message.body = b"task_data"

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            mock_queue.declare = AsyncMock()  # Mock queue.declare() for refresh
            mock_queue.get = AsyncMock(return_value=mock_message)

            await driver.connect()

            @mark.asyncio
            async def test_dequeue_with_poll_seconds(self) -> None:
                """Test dequeue() with poll_seconds > 0 uses manual polling loop and does not hang."""
                # Arrange
                driver = RabbitMQDriver()
                mock_connection = AsyncMock()
                mock_channel = AsyncMock()
                mock_exchange = AsyncMock()
                mock_queue = AsyncMock()
                mock_message = AsyncMock()
                mock_message.body = b"task_data"

                # Patch current_time to advance quickly so the polling loop exits immediately
                with (
                    patch(
                        "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
                        return_value=mock_connection,
                    ),
                    patch("asynctasq.drivers.rabbitmq_driver.current_time", side_effect=[0, 2]),
                ):
                    mock_connection.channel = AsyncMock(return_value=mock_channel)
                    mock_channel.set_qos = AsyncMock()
                    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
                    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
                    mock_queue.bind = AsyncMock()
                    mock_queue_state = MagicMock()
                    mock_queue_state.message_count = 0
                    mock_queue.declare = AsyncMock(return_value=mock_queue_state)
                    mock_queue.get = AsyncMock(return_value=mock_message)

                    await driver.connect()

                    # Act
                    result = await driver.dequeue("default", poll_seconds=1)

                    # Assert
                    assert result == b"task_data"
                    mock_queue.get.assert_called_with(fail=False)

    @mark.asyncio
    async def test_dequeue_with_poll_seconds(self) -> None:
        """Test dequeue() with poll_seconds > 0 uses manual polling loop."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_message = AsyncMock()
        mock_message.body = b"task_data"

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            # Create a mock queue state with message_count
            mock_queue_state = MagicMock()
            mock_queue_state.message_count = 0
            mock_queue.declare = AsyncMock(
                return_value=mock_queue_state
            )  # Mock queue.declare() for refresh
            mock_queue.get = AsyncMock(return_value=mock_message)

            await driver.connect()

            # Act
            result = await driver.dequeue("default", poll_seconds=5)

            # Assert
            assert result == b"task_data"
            # Should use manual polling loop, so get() is called with fail=False (no timeout parameter)
            mock_queue.get.assert_called_with(fail=False)

    @mark.asyncio
    async def test_dequeue_auto_connects(self) -> None:
        """Test dequeue() auto-connects if not connected."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            mock_queue.declare = AsyncMock()  # Mock queue.declare() for refresh
            mock_queue.get = AsyncMock(return_value=None)

            # Act
            await driver.dequeue("default", poll_seconds=0)

            # Assert
            assert driver.connection is not None


@mark.unit
class TestRabbitMQDriverAck:
    """Test RabbitMQDriver.ack() method."""

    @mark.asyncio
    async def test_ack_removes_message(self) -> None:
        """Test ack() acknowledges and removes message."""
        # Arrange
        driver = RabbitMQDriver()
        mock_message = AsyncMock()
        mock_message.ack = AsyncMock()
        receipt_handle = b"task_data"
        driver._receipt_handles[receipt_handle] = mock_message

        # Act
        await driver.ack("default", receipt_handle)

        # Assert
        mock_message.ack.assert_called_once()
        assert receipt_handle not in driver._receipt_handles

    @mark.asyncio
    async def test_ack_with_invalid_receipt_is_safe(self) -> None:
        """Test ack() with invalid receipt handle is safe."""
        # Arrange
        driver = RabbitMQDriver()
        receipt_handle = b"invalid"

        # Act & Assert - should not raise
        await driver.ack("default", receipt_handle)


@mark.unit
class TestRabbitMQDriverNack:
    """Test RabbitMQDriver.nack() method."""

    @mark.asyncio
    async def test_nack_requeues_message(self) -> None:
        """Test nack() requeues message."""
        # Arrange
        driver = RabbitMQDriver()
        mock_message = AsyncMock()
        mock_message.nack = AsyncMock()
        receipt_handle = b"task_data"
        driver._receipt_handles[receipt_handle] = mock_message

        # Act
        await driver.nack("default", receipt_handle)

        # Assert
        mock_message.nack.assert_called_once_with(requeue=True)
        assert receipt_handle not in driver._receipt_handles

    @mark.asyncio
    async def test_nack_with_invalid_receipt_is_safe(self) -> None:
        """Test nack() with invalid receipt handle is safe."""
        # Arrange
        driver = RabbitMQDriver()
        receipt_handle = b"invalid"

        # Act & Assert - should not raise
        await driver.nack("default", receipt_handle)


@mark.unit
class TestRabbitMQDriverGetQueueSize:
    """Test RabbitMQDriver.get_queue_size() method."""

    @mark.asyncio
    async def test_get_queue_size_returns_count(self) -> None:
        """Test get_queue_size() returns message count."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 5
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()

            await driver.connect()

            # Act
            size = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )

            # Assert
            assert size == 5

    @mark.asyncio
    async def test_get_queue_size_with_delayed(self) -> None:
        """Test get_queue_size() includes delayed queue."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 3
        mock_delayed_state = MagicMock()
        mock_delayed_state.message_count = 2
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)
        mock_delayed_queue.declare = AsyncMock(return_value=mock_delayed_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue, mock_delayed_queue])
            mock_queue.bind = AsyncMock()
            mock_delayed_queue.bind = AsyncMock()

            await driver.connect()

            # Act
            size = await driver.get_queue_size(
                "default", include_delayed=True, include_in_flight=False
            )

            # Assert
            assert size == 5  # 3 + 2

    @mark.asyncio
    async def test_get_queue_size_handles_none_message_count(self) -> None:
        """Test get_queue_size() handles None message_count."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = None
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()

            await driver.connect()

            # Act
            size = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )

            # Assert
            assert size == 0

    @mark.asyncio
    async def test_get_queue_size_auto_connects(self) -> None:
        """Test get_queue_size() auto-connects if not connected."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 0
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()

            # Act
            size = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )

            # Assert
            assert driver.connection is not None
            assert size == 0


@mark.unit
class TestRabbitMQDriverEnsureQueue:
    """Test RabbitMQDriver._ensure_queue() method."""

    @mark.asyncio
    async def test_ensure_queue_creates_and_binds_queue(self) -> None:
        """Test _ensure_queue() creates and binds queue."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.bind = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            await driver.connect()

            # Act
            queue = await driver._ensure_queue("test_queue")

            # Assert
            assert queue == mock_queue
            mock_channel.declare_queue.assert_called_once_with(
                "test_queue", durable=True, auto_delete=False
            )
            mock_queue.bind.assert_called_once()

    @mark.asyncio
    async def test_ensure_queue_caches_queue(self) -> None:
        """Test _ensure_queue() caches queue for subsequent calls."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.bind = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            await driver.connect()

            # Act
            queue1 = await driver._ensure_queue("test_queue")
            queue2 = await driver._ensure_queue("test_queue")

            # Assert
            assert queue1 == queue2
            assert queue1 == mock_queue
            mock_channel.declare_queue.assert_called_once()  # Only called once


@mark.unit
class TestRabbitMQDriverEnsureDelayedQueue:
    """Test RabbitMQDriver._ensure_delayed_queue() method."""

    @mark.asyncio
    async def test_ensure_delayed_queue_creates_with_dead_letter(self) -> None:
        """Test _ensure_delayed_queue() creates queue with dead-letter exchange."""
        # Arrange
        driver = RabbitMQDriver()
        driver.exchange_name = "test_exchange"
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_delayed_queue.bind = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)

            await driver.connect()

            # Act
            queue = await driver._ensure_delayed_queue("default")

            # Assert
            assert queue == mock_delayed_queue
            mock_channel.declare_queue.assert_called_once()
            call_kwargs = mock_channel.declare_queue.call_args[1]
            assert call_kwargs["durable"] is True
            assert call_kwargs["auto_delete"] is False
            assert "x-dead-letter-exchange" in call_kwargs["arguments"]
            assert call_kwargs["arguments"]["x-dead-letter-exchange"] == "test_exchange"
            assert call_kwargs["arguments"]["x-dead-letter-routing-key"] == "default"

    @mark.asyncio
    async def test_ensure_delayed_queue_caches_queue(self) -> None:
        """Test _ensure_delayed_queue() caches queue."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_delayed_queue.bind = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)

            await driver.connect()

            # Act
            queue1 = await driver._ensure_delayed_queue("default")
            queue2 = await driver._ensure_delayed_queue("default")

            # Assert
            assert queue1 == queue2
            mock_channel.declare_queue.assert_called_once()


@mark.unit
class TestRabbitMQDriverProcessDelayedTasks:
    """Test RabbitMQDriver._process_delayed_tasks() method."""

    @mark.asyncio
    async def test_process_delayed_tasks_is_noop(self) -> None:
        """Test _process_delayed_tasks() is a no-op (handled by RabbitMQ)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act & Assert - should not raise
        await driver._process_delayed_tasks("default")


@mark.unit
class TestRabbitMQDriverEdgeCases:
    """Test edge cases and error conditions."""

    @mark.asyncio
    async def test_enqueue_negative_delay(self) -> None:
        """Test enqueue() with negative delay (treated as immediate)."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

            await driver.connect()

            # Act
            await driver.enqueue("default", b"task", delay_seconds=-1)

            # Assert - should go to main queue (delay <= 0)
            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            assert call_args[1]["routing_key"] == "default"

    @mark.asyncio
    async def test_receipt_handles_cleared_on_disconnect(self) -> None:
        """Test receipt handles are cleared on disconnect."""
        # Arrange
        driver = RabbitMQDriver()
        mock_message = AsyncMock()
        driver._receipt_handles[b"task1"] = mock_message
        driver._receipt_handles[b"task2"] = mock_message

        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.close = AsyncMock()
            mock_connection.close = AsyncMock()

            await driver.connect()

            # Act
            await driver.disconnect()

            # Assert
            assert len(driver._receipt_handles) == 0

    @mark.asyncio
    async def test_multiple_queues_independent(self) -> None:
        """Test multiple queues are independent."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue1 = AsyncMock()
        mock_queue2 = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue1, mock_queue2])
            mock_queue1.bind = AsyncMock()
            mock_queue2.bind = AsyncMock()

            await driver.connect()

            # Act
            queue1 = await driver._ensure_queue("queue1")
            queue2 = await driver._ensure_queue("queue2")

            # Assert
            assert queue1 == mock_queue1
            assert queue2 == mock_queue2
            assert queue1 != queue2

    @mark.asyncio
    async def test_dequeue_poll_timeout(self) -> None:
        """Test dequeue() returns None after poll timeout."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 0

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            mock_queue.declare = AsyncMock(return_value=mock_queue_state)
            mock_queue.get = AsyncMock(return_value=None)  # Always return None (empty queue)

            await driver.connect()

            # Act
            result = await driver.dequeue("default", poll_seconds=1)  # Short timeout for test

            # Assert
            assert result is None
            # Should have tried to get multiple times
            assert mock_queue.get.call_count > 1

    @mark.asyncio
    async def test_in_flight_counter_management(self) -> None:
        """Test in-flight counter is managed correctly."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_message1 = AsyncMock()
        mock_message1.body = b"task1"
        mock_message1.ack = AsyncMock()
        mock_message2 = AsyncMock()
        mock_message2.body = b"task2"
        mock_message2.nack = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 0

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            mock_queue.declare = AsyncMock(return_value=mock_queue_state)
            # Use a callable side_effect that returns None after the list is exhausted
            messages = [mock_message1, mock_message2, None]
            counter = [0]

            def get_side_effect(*args, **kwargs):
                if counter[0] < len(messages):
                    result = messages[counter[0]]
                    counter[0] += 1
                    return result
                return None

            # Ensure the side effect returns the expected messages for the test
            mock_queue.get = AsyncMock(side_effect=get_side_effect)
            # Patch declare_queue on the mock_channel to always return mock_queue
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            await driver.connect()

            # Act - dequeue two messages
            task1 = await driver.dequeue("default", poll_seconds=0)
            assert task1 is not None

            task2 = await driver.dequeue("default", poll_seconds=0)
            assert task2 is not None

            # Assert - in-flight counter should be 2
            assert driver._in_flight_per_queue.get("default", 0) == 2

            # Act - ack first message
            await driver.ack("default", task1)

            # Assert - in-flight counter should be 1
            assert driver._in_flight_per_queue.get("default", 0) == 1

            # Act - nack second message
            await driver.nack("default", task2)

            # Assert - in-flight counter should be 0
            assert driver._in_flight_per_queue.get("default", 0) == 0

    @mark.asyncio
    async def test_get_queue_size_with_in_flight(self) -> None:
        """Test get_queue_size() includes in-flight messages when requested."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 5
        mock_message = AsyncMock()
        mock_message.body = b"task"

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()
            mock_queue.declare = AsyncMock(return_value=mock_queue_state)
            mock_queue.get = AsyncMock(return_value=mock_message)

            await driver.connect()

            # Dequeue one message to add to in-flight
            await driver.dequeue("default", poll_seconds=0)

            # Act
            size_without = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=False
            )
            size_with = await driver.get_queue_size(
                "default", include_delayed=False, include_in_flight=True
            )

            # Assert
            assert size_without == 5  # Only ready messages
            assert size_with == 6  # Ready + in-flight (1)

    @mark.asyncio
    async def test_process_delayed_tasks_with_ready_tasks(self) -> None:
        """Test _process_delayed_tasks() moves ready tasks to main queue."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_message = AsyncMock()
        # Create a ready task (timestamp in the past)
        import struct
        from time import time as current_time

        ready_at = current_time() - 10  # 10 seconds ago
        ready_at_bytes = struct.pack("d", ready_at)
        mock_message.body = ready_at_bytes + b"task_data"
        mock_message.ack = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)
            mock_delayed_queue.bind = AsyncMock()
            mock_delayed_queue.get = AsyncMock(side_effect=[mock_message, None])
            mock_exchange.publish = AsyncMock()

            await driver.connect()
            # Manually add delayed queue to cache (simulating it was created)
            driver._delayed_queues["default_delayed"] = mock_delayed_queue

            # Act
            await driver._process_delayed_tasks("default")

            # Assert
            # Should have published to main queue
            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            assert call_args[1]["routing_key"] == "default"
            # Should have acked the delayed message
            mock_message.ack.assert_called_once()

    @mark.asyncio
    async def test_process_delayed_tasks_with_not_ready_tasks(self) -> None:
        """Test _process_delayed_tasks() requeues not-ready tasks."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_message = AsyncMock()
        # Create a not-ready task (timestamp in the future)
        import struct
        from time import time as current_time

        ready_at = current_time() + 100  # 100 seconds in future
        ready_at_bytes = struct.pack("d", ready_at)
        mock_message.body = ready_at_bytes + b"task_data"
        mock_message.nack = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)
            mock_delayed_queue.bind = AsyncMock()
            mock_delayed_queue.get = AsyncMock(side_effect=[mock_message, None])

            await driver.connect()
            # Manually add delayed queue to cache
            driver._delayed_queues["default_delayed"] = mock_delayed_queue

            # Act
            await driver._process_delayed_tasks("default")

            # Assert
            # Should NOT have published to main queue
            mock_exchange.publish.assert_not_called()
            # Should have nacked the message for requeuing
            mock_message.nack.assert_called_once_with(requeue=True)

    @mark.asyncio
    async def test_process_delayed_tasks_with_malformed_message(self) -> None:
        """Test _process_delayed_tasks() handles malformed messages (< 8 bytes)."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_message = AsyncMock()
        # Create a malformed message (< 8 bytes)
        mock_message.body = b"short"  # Only 5 bytes, need 8 for timestamp
        mock_message.ack = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)
            mock_delayed_queue.bind = AsyncMock()
            mock_delayed_queue.get = AsyncMock(side_effect=[mock_message, None])
            mock_exchange.publish = AsyncMock()

            await driver.connect()
            # Manually add delayed queue to cache
            driver._delayed_queues["default_delayed"] = mock_delayed_queue

            # Act
            await driver._process_delayed_tasks("default")

            # Assert
            # Should have acked the malformed message to remove it
            mock_message.ack.assert_called_once()
            # Should NOT have published to main queue
            mock_exchange.publish.assert_not_called()

    @mark.asyncio
    async def test_process_delayed_tasks_auto_connects(self) -> None:
        """Test _process_delayed_tasks() auto-connects if needed."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)
            mock_delayed_queue.bind = AsyncMock()
            mock_delayed_queue.get = AsyncMock(return_value=None)

            # Manually add delayed queue to cache without connecting
            driver._delayed_queues["default_delayed"] = mock_delayed_queue

            # Act
            await driver._process_delayed_tasks("default")

            # Assert
            # Should have auto-connected
            assert driver.connection is not None
            assert driver.channel is not None

    @mark.asyncio
    async def test_ensure_delayed_queue_returns_cached(self) -> None:
        """Test _ensure_delayed_queue() returns cached queue."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_delayed_queue = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_delayed_queue)
            mock_delayed_queue.bind = AsyncMock()

            await driver.connect()

            # Manually add to cache
            driver._delayed_queues["test_delayed"] = mock_delayed_queue

            # Act
            result = await driver._ensure_delayed_queue("test")

            # Assert
            assert result == mock_delayed_queue
            # Should not have called declare_queue again
            mock_channel.declare_queue.assert_not_called()

    @mark.asyncio
    async def test_ensure_queue_auto_connects(self) -> None:
        """Test _ensure_queue() auto-connects if needed."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_queue.bind = AsyncMock()

            # Don't connect first, let _ensure_queue do it

            # Act
            result = await driver._ensure_queue("test")

            # Assert
            assert result == mock_queue
            assert driver.connection is not None
            assert driver.channel is not None
            assert driver._delayed_exchange is not None


@mark.unit
class TestRabbitMQDriverGetQueueStats:
    """Test RabbitMQDriver.get_queue_stats() method."""

    @mark.asyncio
    async def test_get_queue_stats_returns_stats(self) -> None:
        """Test get_queue_stats() returns QueueStats."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 5
        mock_delayed_state = MagicMock()
        mock_delayed_state.message_count = 2
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)
        mock_delayed_queue.declare = AsyncMock(return_value=mock_delayed_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue, mock_delayed_queue])
            mock_queue.bind = AsyncMock()
            mock_delayed_queue.bind = AsyncMock()

            await driver.connect()

            # Act
            stats = await driver.get_queue_stats("default")

            # Assert
            assert stats["name"] == "default"
            assert stats["depth"] == 7  # 5 + 2 (main + delayed)
            assert stats["processing"] == 0
            assert stats["completed_total"] == 0
            assert stats["failed_total"] == 0

    @mark.asyncio
    async def test_get_queue_stats_includes_in_flight(self) -> None:
        """Test get_queue_stats() includes in-flight messages in processing count."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_delayed_queue = AsyncMock()
        mock_queue_state = MagicMock()
        mock_queue_state.message_count = 3
        mock_delayed_state = MagicMock()
        mock_delayed_state.message_count = 1
        mock_queue.declare = AsyncMock(return_value=mock_queue_state)
        mock_delayed_queue.declare = AsyncMock(return_value=mock_delayed_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue, mock_delayed_queue])
            mock_queue.bind = AsyncMock()
            mock_delayed_queue.bind = AsyncMock()

            await driver.connect()
            driver._in_flight_per_queue["default"] = 2  # 2 in-flight messages

            # Act
            stats = await driver.get_queue_stats("default")

            # Assert
            assert stats["processing"] == 2
            assert stats["depth"] == 4  # 3 + 1 (main + delayed)


@mark.unit
class TestRabbitMQDriverGetAllQueueNames:
    """Test RabbitMQDriver.get_all_queue_names() method."""

    @mark.asyncio
    async def test_get_all_queue_names_returns_cached_queues(self) -> None:
        """Test get_all_queue_names() returns queue names from cache."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue1 = AsyncMock()
        mock_queue2 = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue1, mock_queue2])
            mock_queue1.bind = AsyncMock()
            mock_queue2.bind = AsyncMock()

            await driver.connect()
            await driver._ensure_queue("queue1")
            await driver._ensure_queue("queue2")

            # Act
            queue_names = await driver.get_all_queue_names()

            # Assert
            assert "queue1" in queue_names
            assert "queue2" in queue_names
            assert len(queue_names) == 2

    @mark.asyncio
    async def test_get_all_queue_names_excludes_delayed_queues(self) -> None:
        """Test get_all_queue_names() excludes delayed queue names."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_delayed_queue = AsyncMock()

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(side_effect=[mock_queue, mock_delayed_queue])
            mock_queue.bind = AsyncMock()
            mock_delayed_queue.bind = AsyncMock()

            await driver.connect()
            await driver._ensure_queue("default")
            await driver._ensure_delayed_queue("default")  # Creates "default_delayed"

            # Act
            queue_names = await driver.get_all_queue_names()

            # Assert
            assert "default" in queue_names
            assert "default_delayed" not in queue_names

    @mark.asyncio
    async def test_get_all_queue_names_returns_empty_when_no_queues(self) -> None:
        """Test get_all_queue_names() returns empty list when no queues accessed."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        queue_names = await driver.get_all_queue_names()

        # Assert
        assert queue_names == []


@mark.unit
class TestRabbitMQDriverGetGlobalStats:
    """Test RabbitMQDriver.get_global_stats() method."""

    @mark.asyncio
    async def test_get_global_stats_aggregates_all_queues(self) -> None:
        """Test get_global_stats() aggregates stats from all queues."""
        # Arrange
        driver = RabbitMQDriver()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue1 = AsyncMock()
        mock_queue2 = AsyncMock()
        mock_delayed_queue1 = AsyncMock()
        mock_delayed_queue2 = AsyncMock()
        mock_queue1_state = MagicMock()
        mock_queue1_state.message_count = 3
        mock_queue2_state = MagicMock()
        mock_queue2_state.message_count = 2
        mock_delayed1_state = MagicMock()
        mock_delayed1_state.message_count = 1
        mock_delayed2_state = MagicMock()
        mock_delayed2_state.message_count = 1
        mock_queue1.declare = AsyncMock(return_value=mock_queue1_state)
        mock_queue2.declare = AsyncMock(return_value=mock_queue2_state)
        mock_delayed_queue1.declare = AsyncMock(return_value=mock_delayed1_state)
        mock_delayed_queue2.declare = AsyncMock(return_value=mock_delayed2_state)

        with patch(
            "asynctasq.drivers.rabbitmq_driver.aio_pika.connect_robust",
            return_value=mock_connection,
        ):
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
            mock_channel.declare_queue = AsyncMock(
                side_effect=[mock_queue1, mock_delayed_queue1, mock_queue2, mock_delayed_queue2]
            )
            mock_queue1.bind = AsyncMock()
            mock_queue2.bind = AsyncMock()
            mock_delayed_queue1.bind = AsyncMock()
            mock_delayed_queue2.bind = AsyncMock()

            await driver.connect()
            await driver._ensure_queue("queue1")
            await driver._ensure_queue("queue2")
            driver._in_flight_per_queue["queue1"] = 1
            driver._in_flight_per_queue["queue2"] = 2

            # Act
            stats = await driver.get_global_stats()

            # Assert
            assert stats["pending"] == 7  # 3 + 2 + 1 + 1 (all queues + delayed)
            assert stats["running"] == 3  # 1 + 2 (in-flight from both queues)
            assert stats["completed"] == 0
            assert stats["failed"] == 0
            assert stats["total"] == 10  # 7 + 3

    @mark.asyncio
    async def test_get_global_stats_returns_zero_when_no_queues(self) -> None:
        """Test get_global_stats() returns zeros when no queues exist."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        stats = await driver.get_global_stats()

        # Assert
        assert stats["pending"] == 0
        assert stats["running"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0
        assert stats["total"] == 0


@mark.unit
class TestRabbitMQDriverTaskManagement:
    """Test RabbitMQDriver task management methods (AMQP limitations)."""

    @mark.asyncio
    async def test_get_running_tasks_returns_empty(self) -> None:
        """Test get_running_tasks() returns empty list (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        tasks = await driver.get_running_tasks(limit=50, offset=0)

        # Assert
        assert tasks == []

    @mark.asyncio
    async def test_get_tasks_returns_empty(self) -> None:
        """Test get_tasks() returns empty list (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        tasks, total = await driver.get_tasks(status="pending", queue="default", limit=50, offset=0)

        # Assert
        assert tasks == []
        assert total == 0

    @mark.asyncio
    async def test_get_task_by_id_returns_none(self) -> None:
        """Test get_task_by_id() returns None (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        task = await driver.get_task_by_id("test-task-id")

        # Assert
        assert task is None

    @mark.asyncio
    async def test_retry_task_returns_false(self) -> None:
        """Test retry_task() returns False (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        result = await driver.retry_task("test-task-id")

        # Assert
        assert result is False

    @mark.asyncio
    async def test_delete_task_returns_false(self) -> None:
        """Test delete_task() returns False (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        result = await driver.delete_task("test-task-id")

        # Assert
        assert result is False

    @mark.asyncio
    async def test_get_worker_stats_returns_empty(self) -> None:
        """Test get_worker_stats() returns empty list (AMQP limitation)."""
        # Arrange
        driver = RabbitMQDriver()

        # Act
        workers = await driver.get_worker_stats()

        # Assert
        assert workers == []


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
