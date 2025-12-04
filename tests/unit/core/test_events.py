"""Tests for the event emission system."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from pytest import fixture, main, mark

from async_task_q.config import Config
from async_task_q.core.events import (
    CompositeEventEmitter,
    EventType,
    LoggingEventEmitter,
    RedisEventEmitter,
    TaskEvent,
    WorkerEvent,
    create_event_emitter,
)


@fixture
def sample_task_event() -> TaskEvent:
    """Create a sample task event for testing."""
    return TaskEvent(
        event_type=EventType.TASK_STARTED,
        task_id="test-task-123",
        task_name="TestTask",
        queue="default",
        worker_id="worker-abc123",
        timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
        attempt=1,
    )


@fixture
def sample_worker_event() -> WorkerEvent:
    """Create a sample worker event for testing."""
    return WorkerEvent(
        event_type=EventType.WORKER_ONLINE,
        worker_id="worker-abc123",
        hostname="test-host",
        timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
        queues=("default", "high-priority"),
        active=5,
        processed=100,
    )


@mark.unit
class TestEventType:
    """Test EventType enum."""

    def test_task_event_types_exist(self) -> None:
        """Test that all task event types are defined."""
        assert EventType.TASK_ENQUEUED == "task_enqueued"
        assert EventType.TASK_STARTED == "task_started"
        assert EventType.TASK_COMPLETED == "task_completed"
        assert EventType.TASK_FAILED == "task_failed"
        assert EventType.TASK_RETRYING == "task_retrying"
        assert EventType.TASK_CANCELLED == "task_cancelled"

    def test_worker_event_types_exist(self) -> None:
        """Test that all worker event types are defined."""
        assert EventType.WORKER_ONLINE == "worker_online"
        assert EventType.WORKER_HEARTBEAT == "worker_heartbeat"
        assert EventType.WORKER_OFFLINE == "worker_offline"


@mark.unit
class TestTaskEvent:
    """Test TaskEvent dataclass."""

    def test_task_event_creation(self, sample_task_event: TaskEvent) -> None:
        """Test that TaskEvent can be created with required fields."""
        assert sample_task_event.event_type == EventType.TASK_STARTED
        assert sample_task_event.task_id == "test-task-123"
        assert sample_task_event.task_name == "TestTask"
        assert sample_task_event.queue == "default"
        assert sample_task_event.worker_id == "worker-abc123"

    def test_task_event_is_frozen(self, sample_task_event: TaskEvent) -> None:
        """Test that TaskEvent is immutable."""
        try:
            sample_task_event.task_id = "new-id"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected

    def test_task_event_with_optional_fields(self) -> None:
        """Test TaskEvent with optional fields populated."""
        event = TaskEvent(
            event_type=EventType.TASK_COMPLETED,
            task_id="test-123",
            task_name="TestTask",
            queue="default",
            worker_id="worker-1",
            duration_ms=1500,
            result={"status": "success"},
        )
        assert event.duration_ms == 1500
        assert event.result == {"status": "success"}

    def test_task_event_with_error_fields(self) -> None:
        """Test TaskEvent with error fields populated."""
        event = TaskEvent(
            event_type=EventType.TASK_FAILED,
            task_id="test-123",
            task_name="TestTask",
            queue="default",
            worker_id="worker-1",
            error="ValueError: Invalid input",
            traceback="Traceback (most recent call last):\n...",
        )
        assert event.error == "ValueError: Invalid input"
        assert event.traceback is not None


@mark.unit
class TestWorkerEvent:
    """Test WorkerEvent dataclass."""

    def test_worker_event_creation(self, sample_worker_event: WorkerEvent) -> None:
        """Test that WorkerEvent can be created with required fields."""
        assert sample_worker_event.event_type == EventType.WORKER_ONLINE
        assert sample_worker_event.worker_id == "worker-abc123"
        assert sample_worker_event.hostname == "test-host"

    def test_worker_event_is_frozen(self, sample_worker_event: WorkerEvent) -> None:
        """Test that WorkerEvent is immutable."""
        try:
            sample_worker_event.worker_id = "new-id"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected

    def test_worker_event_defaults(self) -> None:
        """Test WorkerEvent default values."""
        event = WorkerEvent(
            event_type=EventType.WORKER_HEARTBEAT,
            worker_id="worker-1",
            hostname="host-1",
        )
        assert event.freq == 60.0
        assert event.active == 0
        assert event.processed == 0
        assert event.queues == ()
        assert event.sw_ident == "async-task-q"


@mark.unit
class TestLoggingEventEmitter:
    """Test LoggingEventEmitter."""

    @mark.asyncio
    async def test_emit_task_event_logs(self, sample_task_event: TaskEvent, caplog) -> None:
        """Test that task events are logged."""
        import logging

        with caplog.at_level(logging.INFO):
            emitter = LoggingEventEmitter()
            await emitter.emit_task_event(sample_task_event)

        assert "TaskEvent" in caplog.text
        assert "task_started" in caplog.text
        assert "test-task-123" in caplog.text

    @mark.asyncio
    async def test_emit_worker_event_logs(self, sample_worker_event: WorkerEvent, caplog) -> None:
        """Test that worker events are logged."""
        import logging

        with caplog.at_level(logging.INFO):
            emitter = LoggingEventEmitter()
            await emitter.emit_worker_event(sample_worker_event)

        assert "WorkerEvent" in caplog.text
        assert "worker_online" in caplog.text
        assert "worker-abc123" in caplog.text

    @mark.asyncio
    async def test_close_is_noop(self) -> None:
        """Test that close does nothing."""
        emitter = LoggingEventEmitter()
        await emitter.close()  # Should not raise


@mark.unit
class TestRedisEventEmitter:
    """Test RedisEventEmitter."""

    def test_init_uses_config_events_redis_url(self) -> None:
        """Test that events_redis_url from config is used first."""
        mock_config = Config(
            events_redis_url="redis://events:6379",
            redis_url="redis://queue:6379",
            events_channel="custom:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        assert emitter.redis_url == "redis://events:6379"
        assert emitter.channel == "custom:events"

    def test_init_falls_back_to_redis_url(self) -> None:
        """Test fallback to redis_url when events_redis_url is None."""
        mock_config = Config(
            events_redis_url=None,
            redis_url="redis://queue:6379",
            events_channel="async_task_q:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        assert emitter.redis_url == "redis://queue:6379"

    def test_init_with_explicit_params_overrides_config(self) -> None:
        """Test that explicit parameters override config values."""
        mock_config = Config(
            events_redis_url="redis://events:6379",
            redis_url="redis://queue:6379",
            events_channel="config:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter(
                redis_url="redis://explicit:6379", channel="explicit:channel"
            )

        assert emitter.redis_url == "redis://explicit:6379"
        assert emitter.channel == "explicit:channel"

    @mark.asyncio
    async def test_emit_task_event_publishes_to_redis(self, sample_task_event: TaskEvent) -> None:
        """Test that task events are published to Redis."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        # Mock the Redis client
        mock_client = AsyncMock()
        emitter._client = mock_client

        await emitter.emit_task_event(sample_task_event)

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == "test:events"
        assert isinstance(call_args[0][1], bytes)  # msgpack serialized

    @mark.asyncio
    async def test_emit_worker_event_publishes_to_redis(
        self, sample_worker_event: WorkerEvent
    ) -> None:
        """Test that worker events are published to Redis."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        mock_client = AsyncMock()
        emitter._client = mock_client

        await emitter.emit_worker_event(sample_worker_event)

        mock_client.publish.assert_called_once()

    @mark.asyncio
    async def test_emit_handles_publish_error_gracefully(
        self, sample_task_event: TaskEvent, caplog
    ) -> None:
        """Test that publish errors are caught and logged."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        mock_client = AsyncMock()
        mock_client.publish.side_effect = Exception("Connection failed")
        emitter._client = mock_client

        # Should not raise
        await emitter.emit_task_event(sample_task_event)

        assert "Failed to publish task event" in caplog.text

    @mark.asyncio
    async def test_close_closes_client(self) -> None:
        """Test that close properly closes the Redis client."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        mock_client = AsyncMock()
        emitter._client = mock_client

        await emitter.close()

        mock_client.aclose.assert_called_once()
        assert emitter._client is None

    @mark.asyncio
    async def test_close_without_client_is_safe(self) -> None:
        """Test that close works even if client was never connected."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        await emitter.close()  # Should not raise

    def test_serialize_event_converts_types(self, sample_task_event: TaskEvent) -> None:
        """Test that event serialization handles type conversions."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        result = emitter._serialize_event(sample_task_event)

        assert isinstance(result, bytes)
        # Verify it's valid msgpack by deserializing
        import msgpack

        data = msgpack.unpackb(result)
        assert data["event_type"] == "task_started"
        assert data["task_id"] == "test-task-123"
        assert isinstance(data["timestamp"], str)  # ISO format string

    def test_serialize_worker_event_converts_queues_tuple(
        self, sample_worker_event: WorkerEvent
    ) -> None:
        """Test that queues tuple is converted to list for msgpack."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        result = emitter._serialize_event(sample_worker_event)

        import msgpack

        data = msgpack.unpackb(result)
        assert isinstance(data["queues"], list)
        assert data["queues"] == ["default", "high-priority"]


@mark.unit
class TestCompositeEventEmitter:
    """Test CompositeEventEmitter."""

    @mark.asyncio
    async def test_emits_to_all_emitters(self, sample_task_event: TaskEvent) -> None:
        """Test that events are emitted to all registered emitters."""
        emitter1 = AsyncMock()
        emitter2 = AsyncMock()

        composite = CompositeEventEmitter([emitter1, emitter2])
        await composite.emit_task_event(sample_task_event)

        emitter1.emit_task_event.assert_called_once_with(sample_task_event)
        emitter2.emit_task_event.assert_called_once_with(sample_task_event)

    @mark.asyncio
    async def test_continues_on_emitter_error(self, sample_task_event: TaskEvent, caplog) -> None:
        """Test that one failing emitter doesn't block others."""
        emitter1 = AsyncMock()
        emitter1.emit_task_event.side_effect = Exception("Emitter 1 failed")
        emitter2 = AsyncMock()

        composite = CompositeEventEmitter([emitter1, emitter2])
        await composite.emit_task_event(sample_task_event)

        # emitter2 should still be called
        emitter2.emit_task_event.assert_called_once_with(sample_task_event)
        assert "Failed to emit task event" in caplog.text

    @mark.asyncio
    async def test_close_closes_all_emitters(self) -> None:
        """Test that close is called on all emitters."""
        emitter1 = AsyncMock()
        emitter2 = AsyncMock()

        composite = CompositeEventEmitter([emitter1, emitter2])
        await composite.close()

        emitter1.close.assert_called_once()
        emitter2.close.assert_called_once()

    @mark.asyncio
    async def test_close_continues_on_error(self, caplog) -> None:
        """Test that close continues even if one emitter fails."""
        emitter1 = AsyncMock()
        emitter1.close.side_effect = Exception("Close failed")
        emitter2 = AsyncMock()

        composite = CompositeEventEmitter([emitter1, emitter2])
        await composite.close()

        emitter2.close.assert_called_once()
        assert "Failed to close emitter" in caplog.text


@mark.unit
class TestCreateEventEmitter:
    """Test create_event_emitter factory function."""

    def test_returns_logging_emitter_when_redis_not_available(self) -> None:
        """Test fallback to logging emitter when redis not installed."""
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            # Force ImportError by patching the import
            with patch("async_task_q.core.events.create_event_emitter") as mock_factory:
                mock_factory.return_value = LoggingEventEmitter()
                emitter = mock_factory()
                assert isinstance(emitter, LoggingEventEmitter)

    def test_returns_composite_when_redis_available_and_logging_enabled(self) -> None:
        """Test that composite emitter is returned with both logging and Redis."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with (
            patch("async_task_q.core.events.get_global_config", return_value=mock_config),
            patch("redis.asyncio.Redis"),
        ):
            emitter = create_event_emitter(include_logging=True)
            assert isinstance(emitter, CompositeEventEmitter)
            assert len(emitter.emitters) == 2

    def test_returns_redis_only_when_logging_disabled(self) -> None:
        """Test that only Redis emitter is returned when logging disabled."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="test:events",
        )

        with (
            patch("async_task_q.core.events.get_global_config", return_value=mock_config),
            patch("redis.asyncio.Redis"),
        ):
            emitter = create_event_emitter(include_logging=False)
            assert isinstance(emitter, RedisEventEmitter)

    def test_passes_redis_url_to_emitter(self) -> None:
        """Test that explicit redis_url is passed to RedisEventEmitter."""
        mock_config = Config(
            events_redis_url="redis://config:6379",
            events_channel="test:events",
        )

        with (
            patch("async_task_q.core.events.get_global_config", return_value=mock_config),
            patch("redis.asyncio.Redis"),
        ):
            emitter = create_event_emitter(redis_url="redis://explicit:6379", include_logging=False)
            assert isinstance(emitter, RedisEventEmitter)
            assert emitter.redis_url == "redis://explicit:6379"

    def test_passes_channel_to_emitter(self) -> None:
        """Test that explicit channel is passed to RedisEventEmitter."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="config:events",
        )

        with (
            patch("async_task_q.core.events.get_global_config", return_value=mock_config),
            patch("redis.asyncio.Redis"),
        ):
            emitter = create_event_emitter(channel="explicit:channel", include_logging=False)
            assert isinstance(emitter, RedisEventEmitter)
            assert emitter.channel == "explicit:channel"


@mark.unit
class TestEventsRedisUrlConfig:
    """Test the events_redis_url configuration fallback behavior."""

    def test_events_redis_url_takes_priority(self) -> None:
        """Test that events_redis_url is used over redis_url."""
        mock_config = Config(
            events_redis_url="redis://events-server:6379",
            redis_url="redis://queue-server:6379",
            events_channel="custom:channel",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        assert emitter.redis_url == "redis://events-server:6379"

    def test_falls_back_to_redis_url_when_events_url_none(self) -> None:
        """Test fallback to redis_url when events_redis_url is None."""
        mock_config = Config(
            events_redis_url=None,
            redis_url="redis://queue-server:6379",
            events_channel="async_task_q:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        assert emitter.redis_url == "redis://queue-server:6379"

    def test_explicit_param_overrides_all_config(self) -> None:
        """Test that explicit redis_url param overrides both config values."""
        mock_config = Config(
            events_redis_url="redis://events-server:6379",
            redis_url="redis://queue-server:6379",
            events_channel="config:channel",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter(redis_url="redis://param:6379")

        assert emitter.redis_url == "redis://param:6379"

    def test_events_channel_from_config(self) -> None:
        """Test that events_channel is read from config."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="my-app:events",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter()

        assert emitter.channel == "my-app:events"

    def test_channel_param_overrides_config(self) -> None:
        """Test that explicit channel param overrides config."""
        mock_config = Config(
            events_redis_url="redis://localhost:6379",
            events_channel="config:channel",
        )

        with patch("async_task_q.core.events.get_global_config", return_value=mock_config):
            emitter = RedisEventEmitter(channel="param:channel")

        assert emitter.channel == "param:channel"


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
