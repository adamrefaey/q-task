"""Event emission system for task queue monitoring.

This module provides a comprehensive event system for real-time monitoring
of task and worker lifecycle events. Events are published to Redis Pub/Sub
for consumption by the async-task-q-monitor package.

Task Events:
    - task_enqueued: Task added to queue, awaiting execution
    - task_started: Worker began executing the task
    - task_completed: Task finished successfully
    - task_failed: Task failed after exhausting retries
    - task_retrying: Task failed but will be retried
    - task_cancelled: Task was cancelled/revoked before completion

Worker Events:
    - worker_online: Worker started and ready to process tasks
    - worker_heartbeat: Periodic status update (default: every 60s)
    - worker_offline: Worker shutting down gracefully

Architecture:
    Events flow from workers → Redis Pub/Sub → Monitor → WebSocket → UI

Example:
    >>> emitter = create_event_emitter(redis_url="redis://localhost:6379")
    >>> await emitter.emit_task_event(TaskEvent(
    ...     event_type=EventType.TASK_STARTED,
    ...     task_id="abc123",
    ...     task_name="SendEmailTask",
    ...     queue="default",
    ...     worker_id="worker-1"
    ... ))
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any, Protocol

import msgpack

from async_task_q.config import get_global_config

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Event types for task and worker lifecycle tracking.

    Each event type corresponds to a specific state change in the
    task queue lifecycle, enabling real-time monitoring and metrics.
    """

    # Task lifecycle events
    TASK_ENQUEUED = "task_enqueued"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_RETRYING = "task_retrying"
    TASK_CANCELLED = "task_cancelled"

    # Worker lifecycle events
    WORKER_ONLINE = "worker_online"
    WORKER_HEARTBEAT = "worker_heartbeat"
    WORKER_OFFLINE = "worker_offline"


@dataclass(frozen=True)
class TaskEvent:
    """Immutable event emitted during task lifecycle.

    Attributes:
        event_type: The type of task event
        task_id: Unique task identifier (UUID)
        task_name: Name of the task class/function
        queue: Queue the task was dispatched to
        worker_id: Worker processing the task (if applicable)
        timestamp: When the event occurred (UTC)
        attempt: Current retry attempt number (1-based)
        duration_ms: Execution duration in milliseconds (for completed/failed)
        result: Task result (for completed events, optional)
        error: Error message (for failed/retrying events)
        traceback: Full traceback string (for failed events)
    """

    event_type: EventType
    task_id: str
    task_name: str
    queue: str
    worker_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    attempt: int = 1
    duration_ms: int | None = None
    result: Any = None
    error: str | None = None
    traceback: str | None = None


@dataclass(frozen=True)
class WorkerEvent:
    """Immutable event emitted during worker lifecycle.

    Worker events track the state of worker processes, enabling:
    - Health monitoring via heartbeats
    - Load balancing decisions based on active task counts
    - Metrics aggregation across the worker pool

    Attributes:
        event_type: The type of worker event (online/heartbeat/offline)
        worker_id: Unique worker identifier (e.g., "worker-a1b2c3d4")
        hostname: System hostname where worker runs
        timestamp: When the event occurred (UTC)
        freq: Heartbeat frequency in seconds (default 60)
        active: Number of currently executing tasks
        processed: Total tasks processed by this worker
        queues: Queue names the worker consumes from
        sw_ident: Software identifier ("async-task-q")
        sw_ver: Software version string
        uptime_seconds: How long the worker has been running
    """

    event_type: EventType
    worker_id: str
    hostname: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    freq: float = 60.0  # Heartbeat frequency in seconds
    active: int = 0  # Currently executing tasks
    processed: int = 0  # Total tasks processed
    queues: tuple[str, ...] = ()  # Use tuple for immutability
    sw_ident: str = "async-task-q"
    sw_ver: str = "1.0.0"
    uptime_seconds: int | None = None


class EventEmitter(Protocol):
    """Protocol for event emission - allows multiple implementations.

    Using Protocol (PEP 544) for structural typing instead of ABC,
    which is more Pythonic and allows duck typing without inheritance.

    Implementations:
    - LoggingEventEmitter: Logs events (default, no dependencies)
    - RedisEventEmitter: Publishes to Redis Pub/Sub
    - CompositeEventEmitter: Combines multiple emitters
    """

    async def emit_task_event(self, event: TaskEvent) -> None:
        """Emit a task lifecycle event."""
        ...

    async def emit_worker_event(self, event: WorkerEvent) -> None:
        """Emit a worker lifecycle event."""
        ...

    async def close(self) -> None:
        """Close any connections."""
        ...


class LoggingEventEmitter:
    """Simple event emitter that logs events (default, no dependencies).

    This is the default emitter when Redis is not configured. Useful for
    development, debugging, or when monitoring is not required.
    """

    async def emit_task_event(self, event: TaskEvent) -> None:
        """Log a task event at INFO level."""
        logger.info(
            "TaskEvent: %s task=%s queue=%s worker=%s",
            event.event_type.value,
            event.task_id,
            event.queue,
            event.worker_id,
        )

    async def emit_worker_event(self, event: WorkerEvent) -> None:
        """Log a worker event at INFO level."""
        logger.info(
            "WorkerEvent: %s worker=%s active=%d processed=%d",
            event.event_type.value,
            event.worker_id,
            event.active,
            event.processed,
        )

    async def close(self) -> None:
        """No-op for logging emitter."""


class RedisEventEmitter:
    """Publishes events to Redis Pub/Sub for monitor consumption.

    Uses msgpack for efficient serialization (matches existing serializers).
    Lazy initialization prevents import-time side effects.

    Configuration:
        The Redis URL for events is read from global config in this order:
        1. events_redis_url if explicitly set (async_task_q_EVENTS_REDIS_URL env var)
        2. Falls back to redis_url (async_task_q_REDIS_URL env var)

        The Pub/Sub channel is configured via events_channel in global config
        (async_task_q_EVENTS_CHANNEL env var, default: async_task_q:events).

        This allows using a different Redis instance for events/monitoring
        than the one used for the queue driver.

    Requirements:
        - Redis server running and accessible
        - redis[hiredis] package installed (included with async-task-q[monitor])

    The monitor package subscribes to the events channel and broadcasts
    received events to WebSocket clients for real-time updates.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        channel: str | None = None,
    ) -> None:
        """Initialize the Redis event emitter.

        Args:
            redis_url: Redis connection URL (default from config's events_redis_url or redis_url)
            channel: Pub/Sub channel name (default from config's events_channel)
        """
        config = get_global_config()
        # Use events_redis_url if set, otherwise fall back to redis_url
        self.redis_url = redis_url or config.events_redis_url or config.redis_url
        self.channel = channel or config.events_channel
        self._client: Redis | None = None

    async def _ensure_connected(self) -> None:
        """Lazily initialize Redis connection on first use."""
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self.redis_url, decode_responses=False)

    def _serialize_event(self, event: TaskEvent | WorkerEvent) -> bytes:
        """Serialize an event to msgpack bytes.

        Converts the frozen dataclass to a dict with JSON-serializable values:
        - EventType enum → string value
        - datetime → ISO 8601 string
        - tuple → list (msgpack doesn't support tuples)
        """
        event_dict = asdict(event)
        event_dict["event_type"] = event.event_type.value
        event_dict["timestamp"] = event.timestamp.isoformat()

        # Convert tuple to list for msgpack compatibility
        if "queues" in event_dict and isinstance(event_dict["queues"], tuple):
            event_dict["queues"] = list(event_dict["queues"])

        result = msgpack.packb(event_dict, use_bin_type=True)
        if result is None:
            raise ValueError("msgpack.packb returned None")
        return result

    async def emit_task_event(self, event: TaskEvent) -> None:
        """Publish a task event to Redis Pub/Sub."""
        await self._ensure_connected()
        assert self._client is not None

        try:
            message = self._serialize_event(event)
            await self._client.publish(self.channel, message)
        except Exception as e:
            logger.warning("Failed to publish task event to Redis: %s", e)

    async def emit_worker_event(self, event: WorkerEvent) -> None:
        """Publish a worker event to Redis Pub/Sub."""
        await self._ensure_connected()
        assert self._client is not None

        try:
            message = self._serialize_event(event)
            await self._client.publish(self.channel, message)
        except Exception as e:
            logger.warning("Failed to publish worker event to Redis: %s", e)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None


class CompositeEventEmitter:
    """Emits events to multiple emitters (e.g., logging + Redis).

    Useful for maintaining log visibility while also publishing to
    Redis for the monitoring UI.

    Exceptions in individual emitters are caught and logged to prevent
    one failing emitter from blocking others.
    """

    def __init__(self, emitters: list[EventEmitter]) -> None:
        """Initialize with a list of emitters.

        Args:
            emitters: List of EventEmitter implementations to delegate to
        """
        self.emitters = emitters

    async def emit_task_event(self, event: TaskEvent) -> None:
        """Emit task event to all registered emitters."""
        for emitter in self.emitters:
            try:
                await emitter.emit_task_event(event)
            except Exception as e:
                logger.warning("Failed to emit task event via %s: %s", type(emitter).__name__, e)

    async def emit_worker_event(self, event: WorkerEvent) -> None:
        """Emit worker event to all registered emitters."""
        for emitter in self.emitters:
            try:
                await emitter.emit_worker_event(event)
            except Exception as e:
                logger.warning("Failed to emit worker event via %s: %s", type(emitter).__name__, e)

    async def close(self) -> None:
        """Close all emitters."""
        for emitter in self.emitters:
            try:
                await emitter.close()
            except Exception as e:
                logger.warning("Failed to close emitter %s: %s", type(emitter).__name__, e)


def create_event_emitter(
    redis_url: str | None = None,
    channel: str | None = None,
    *,
    include_logging: bool = True,
) -> EventEmitter:
    """Factory function to create an appropriate event emitter.

    Creates a Redis emitter if redis package is available, optionally combined
    with a logging emitter for visibility.

    Args:
        redis_url: Redis URL (defaults to config's events_redis_url, then redis_url)
        channel: Pub/Sub channel (defaults to config's events_channel)
        include_logging: Whether to also log events (default True)

    Returns:
        An EventEmitter instance (single or composite)

    Note:
        To enable Redis event emission for monitor integration:
        1. Install with monitor extra: pip install async-task-q[monitor]
        2. Ensure a Redis server is running and accessible
        3. Configure via set_global_config() or environment variables:
           - events_redis_url / async_task_q_EVENTS_REDIS_URL (dedicated events Redis)
           - redis_url / async_task_q_REDIS_URL (fallback if events_redis_url not set)
           - events_channel / async_task_q_EVENTS_CHANNEL (Pub/Sub channel name)
    """
    emitters: list[EventEmitter] = []

    # Always add logging emitter if requested
    if include_logging:
        emitters.append(LoggingEventEmitter())

    # Try to add Redis emitter if redis package is available
    try:
        from redis.asyncio import Redis as _  # noqa: F401

        redis_emitter = RedisEventEmitter(redis_url=redis_url, channel=channel)
        emitters.append(redis_emitter)
        logger.debug("Redis event emitter configured for channel: %s", redis_emitter.channel)
    except ImportError:
        logger.debug(
            "Redis package not available. Install async-task-q[monitor] for Redis event emission."
        )

    if len(emitters) == 0:
        return LoggingEventEmitter()
    if len(emitters) == 1:
        return emitters[0]
    return CompositeEventEmitter(emitters)
