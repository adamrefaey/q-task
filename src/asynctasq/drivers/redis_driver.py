from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from time import time
from typing import Any

from redis.asyncio import Redis

from asynctasq.core.models import QueueStats, WorkerInfo

from .base_driver import BaseDriver


async def maybe_await(result: Any) -> Any:
    """Helper to handle redis-py's inconsistent type stubs.

    Redis-py has inline types but they're incomplete/incorrect for asyncio.
    This helper checks if the result is awaitable and awaits it if so.

    Note on Type Stubs:
        redis-py defines EncodableT = Union[bytes, bytearray, memoryview, str, int, float]
        but some command stubs incorrectly narrow parameters to just `str`:
        - lrem(value: str) should be lrem(value: EncodableT)

        Runtime behavior is correct - these commands accept bytes when decode_responses=False.
        We use `# type: ignore[arg-type]` for these known redis-py type stub bugs.

    Args:
        result: Result from redis-py operation

    Returns:
        The awaited result if awaitable, otherwise the result itself
    """
    if isawaitable(result):
        return await result
    return result


@dataclass
class RedisDriver(BaseDriver):
    """Redis-based queue driver using Lists for immediate tasks and Sorted Sets for delayed tasks.

    Architecture:
        - Immediate tasks: Redis List at "queue:{name}" (LPUSH/LMOVE for FIFO)
        - Processing tasks: Redis List at "queue:{name}:processing" (in-flight tracking)
        - Delayed tasks: Sorted Set at "queue:{name}:delayed" (score = Unix timestamp)
        - Ready delayed tasks are moved to main queue atomically via pipeline transaction

    Design Decisions:
        - Reliable Queue Pattern: Uses LMOVE to atomically move tasks to processing list
        - Processing list enables crash recovery and prevents nack-after-ack bugs
        - Sorted sets over TTL/Lua: Simpler, atomic, no external dependencies
        - Pipeline with MULTI/EXEC: Prevents duplicate processing during delayed→main transfer
        - RESP3 protocol: Better performance than RESP2 (requires Redis 6.0+)

    Requirements:
        - Python 3.11+, redis-py 7.0+, Redis server 6.2.0+ (for LMOVE command)
    """

    url: str = "redis://localhost:6379"
    password: str | None = None
    db: int = 0
    max_connections: int = 10
    client: Redis | None = field(default=None, init=False, repr=False)

    async def connect(self) -> None:
        """Initialize Redis connection with pooling (connection is lazy)."""
        if self.client is not None:
            return

        self.client = Redis.from_url(
            self.url,
            password=self.password,
            db=self.db,
            decode_responses=False,  # Return bytes, not strings
            max_connections=self.max_connections,
            protocol=3,  # Use RESP3 protocol for better performance
        )

    async def disconnect(self) -> None:
        """Close all connections and cleanup resources."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def enqueue(self, queue_name: str, task_data: bytes, delay_seconds: int = 0) -> None:
        """Add task to queue.

        Args:
            queue_name: Name of the queue
            task_data: Serialized task data
            delay_seconds: Seconds to delay task visibility (0 = immediate)

        Implementation:
            - Immediate: LPUSH to list for O(1) insertion
            - Delayed: ZADD to sorted set with score = current_time + delay_seconds
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        if delay_seconds > 0:
            # Calculate absolute execution time (Unix timestamp)
            # This is the "score" that Redis will use for sorting
            process_at: float = time() + delay_seconds

            # ZADD adds to sorted set - Redis automatically maintains sort order
            # Mapping format: {member: score} where member=task_data, score=process_at
            await maybe_await(
                self.client.zadd(f"queue:{queue_name}:delayed", {task_data: process_at})
            )
        else:
            # LPUSH adds to left of list - workers RPOP from right (FIFO)
            await maybe_await(self.client.lpush(f"queue:{queue_name}", task_data))

    async def dequeue(self, queue_name: str, poll_seconds: int = 0) -> bytes | None:
        """Retrieve next task from queue using Reliable Queue pattern.

        Args:
            queue_name: Name of the queue
            poll_seconds: Seconds to poll for task (0 = non-blocking)

        Returns:
            Serialized task data or None if queue empty

        Implementation:
            Uses LMOVE to atomically move task from main queue to processing list.
            This implements Redis's "Reliable Queue" pattern for crash recovery.
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        # Move any ready delayed tasks to main queue
        await self._process_delayed_tasks(queue_name)

        main_key = f"queue:{queue_name}"
        processing_key = f"queue:{queue_name}:processing"

        # Atomically move from main queue to processing list (Reliable Queue pattern)
        if poll_seconds > 0:
            # BLMOVE: blocking version with timeout
            result: bytes | None = await maybe_await(
                self.client.blmove(main_key, processing_key, poll_seconds, "RIGHT", "LEFT")
            )
            return result
        else:
            # LMOVE: non-blocking version
            return await maybe_await(self.client.lmove(main_key, processing_key, "RIGHT", "LEFT"))

    async def ack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Acknowledge successful task processing (remove from processing list).

        Args:
            queue_name: Name of the queue
            receipt_handle: Task data from dequeue

        Implementation:
            Uses LREM to remove task from processing list. Idempotent operation.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        processing_key = f"queue:{queue_name}:processing"
        # Remove task from processing list (count=1 removes first occurrence)
        # redis-py's lrem type stub expects str, but runtime accepts bytes (see maybe_await docs)
        await maybe_await(self.client.lrem(processing_key, 1, receipt_handle))  # type: ignore[arg-type]

    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject task and re-queue for immediate retry.

        Args:
            queue_name: Name of the queue
            receipt_handle: Task data from dequeue

        Implementation:
            Only requeues if task exists in processing list (prevents nack-after-ack).
            First checks if task is in processing, then moves it back if found.
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        processing_key = f"queue:{queue_name}:processing"
        main_key = f"queue:{queue_name}"

        # Only requeue if task exists in processing list (prevents nack-after-ack)
        # LREM returns count of removed items: 0 if not found, 1 if found and removed
        # redis-py's lrem type stub expects str, but runtime accepts bytes (see maybe_await docs)
        removed_count: int = await maybe_await(
            self.client.lrem(processing_key, 1, receipt_handle)  # type: ignore[arg-type]
        )

        # Only add back to queue if task was actually in processing list
        # This prevents nack-after-ack from re-adding already completed tasks
        if removed_count > 0:
            await maybe_await(self.client.lpush(main_key, receipt_handle))

    async def get_queue_size(
        self,
        queue_name: str,
        include_delayed: bool,
        include_in_flight: bool,
    ) -> int:
        """Get number of tasks in queue.

        Args:
            queue_name: Name of the queue
            include_delayed: Include delayed tasks in count
            include_in_flight: Include in-flight tasks in count

        Returns:
            Task count based on parameters
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        size: int = await maybe_await(self.client.llen(f"queue:{queue_name}"))

        if include_delayed:
            delayed_size: int = await maybe_await(self.client.zcard(f"queue:{queue_name}:delayed"))
            size += delayed_size

        if include_in_flight:
            processing_size: int = await maybe_await(
                self.client.llen(f"queue:{queue_name}:processing")
            )
            size += processing_size

        return size

    async def _process_delayed_tasks(self, queue_name: str) -> None:
        """Move ready delayed tasks to main queue atomically.

        Process:
            1. Query sorted set for tasks with score <= current_time (ZRANGEBYSCORE)
            2. If ready tasks found, use pipeline transaction to:
               - LPUSH tasks to main queue
               - ZREMRANGEBYSCORE to remove from delayed queue
            3. MULTI/EXEC ensures atomicity (prevents duplicate processing)

        Args:
            queue_name: Name of the queue
        """
        now: float = time()
        delayed_key: str = f"queue:{queue_name}:delayed"
        main_key: str = f"queue:{queue_name}"

        assert self.client is not None

        # Get all tasks ready to process (score <= current time)
        ready_tasks: list[bytes] = await self.client.zrangebyscore(delayed_key, min="-inf", max=now)

        if ready_tasks:
            # Move tasks atomically: add to main queue and remove from delayed queue
            async with self.client.pipeline(transaction=True) as pipe:
                pipe.lpush(main_key, *ready_tasks)
                pipe.zremrangebyscore(delayed_key, 0, now)
                await pipe.execute()

    # --- Metadata / Inspection methods -------------------------------------------------

    async def get_queue_stats(self, queue: str) -> QueueStats:
        """
        Basic stats for a specific queue.

        Note: This implementation uses simple counters derived from list/zset sizes.
        More advanced stats (avg_duration, throughput) are not collected here and
        will return defaults.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        depth = int(await maybe_await(self.client.llen(f"queue:{queue}")))
        processing = int(await maybe_await(self.client.llen(f"queue:{queue}:processing")))
        completed_raw = await maybe_await(self.client.get(f"queue:{queue}:stats:completed"))
        completed_total = int(completed_raw or 0)
        failed_raw = await maybe_await(self.client.get(f"queue:{queue}:stats:failed"))
        failed_total = int(failed_raw or 0)

        return QueueStats(
            name=queue,
            depth=depth,
            processing=processing,
            completed_total=completed_total,
            failed_total=failed_total,
            avg_duration_ms=None,
            throughput_per_minute=None,
        )

    async def get_all_queue_names(self) -> list[str]:
        """Return all queue names discovered by key patterns.

        Uses SCAN to avoid blocking Redis in production.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues: set[str] = set()

        # Use scan_iter helper when available; redis-py provides scan_iter as sync and async
        # but to keep compatibility we'll use scan until cursor==0
        cur = 0
        while True:
            cur, keys = await maybe_await(self.client.scan(cur))
            for k in keys:
                # keys are bytes because decode_responses=False
                if isinstance(k, bytes):
                    k = k.decode()
                if k.startswith("queue:"):
                    # strip prefix and any suffix like :processing or :delayed
                    name = k.split(":")[1]
                    queues.add(name)
            if cur == 0:
                break

        return sorted(queues)

    async def get_global_stats(self) -> dict[str, int]:
        """Aggregate simple global stats across all queues.

        Implementation is intentionally conservative: sums per-queue counters.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = await self.get_all_queue_names()
        pending = 0
        running = 0
        completed = 0
        failed = 0

        for q in queues:
            pending += int(await maybe_await(self.client.llen(f"queue:{q}")))
            running += int(await maybe_await(self.client.llen(f"queue:{q}:processing")))
            completed_raw = await maybe_await(self.client.get(f"queue:{q}:stats:completed"))
            completed += int(completed_raw or 0)
            failed_raw = await maybe_await(self.client.get(f"queue:{q}:stats:failed"))
            failed += int(failed_raw or 0)

        total = pending + running + completed + failed
        return {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "total": total,
        }

    async def get_running_tasks(self, limit: int = 50, offset: int = 0) -> list[tuple[bytes, str]]:
        """Return raw task bytes for tasks currently in processing lists.

        Returns:
            List of (raw_bytes, queue_name) tuples for running tasks
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = await self.get_all_queue_names()
        running: list[tuple[bytes, str]] = []

        for q in queues:
            processing_key = f"queue:{q}:processing"
            items = await maybe_await(self.client.lrange(processing_key, 0, -1))
            for raw in items:
                if isinstance(raw, (bytes, bytearray)):
                    running.append((bytes(raw), q))

        # Apply pagination
        return running[offset : offset + limit]

    async def get_tasks(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[bytes, str, str]], int]:
        """Return raw serialized task bytes with queue and status metadata.

        Returns raw msgpack bytes as stored in Redis, allowing the caller
        to deserialize using the appropriate serializer.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = [queue] if queue else await self.get_all_queue_names()
        results: list[tuple[bytes, str, str]] = []

        for q in queues:
            # pending tasks
            if status is None or status == "pending":
                pending_items = await maybe_await(self.client.lrange(f"queue:{q}", 0, -1))
                for raw in pending_items:
                    if isinstance(raw, (bytes, bytearray)):
                        results.append((bytes(raw), q, "pending"))

            # running tasks
            if status is None or status == "running":
                processing_items = await maybe_await(
                    self.client.lrange(f"queue:{q}:processing", 0, -1)
                )
                for raw in processing_items:
                    if isinstance(raw, (bytes, bytearray)):
                        results.append((bytes(raw), q, "running"))

        total = len(results)
        paged = results[offset : offset + limit]
        return paged, total

    async def get_task_by_id(self, task_id: str) -> bytes | None:
        """Best-effort lookup by scanning pending and processing lists for matching id.

        Returns raw msgpack bytes or None if not found.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = await self.get_all_queue_names()

        for q in queues:
            for key_suffix in ("", ":processing"):
                items = await maybe_await(self.client.lrange(f"queue:{q}{key_suffix}", 0, -1))
                for raw in items:
                    if isinstance(raw, (bytes, bytearray)):
                        # We need to deserialize to check task_id, but return raw bytes
                        # For now, scan by deserializing temporarily
                        try:
                            from msgpack import unpackb

                            task_dict = unpackb(raw, raw=False)
                            if task_dict.get("task_id") == task_id:
                                return bytes(raw)
                        except Exception:
                            continue

        return None

    async def retry_task(self, task_id: str) -> bool:
        """Retry a failed task by moving it back to the queue.

        This implementation searches for the task in a dead-letter list `queue:{q}:dead`.
        If found, it LPUSHes it back to the main queue and increments attempt counter.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = await self.get_all_queue_names()

        for q in queues:
            dead_key = f"queue:{q}:dead"
            items = await maybe_await(self.client.lrange(dead_key, 0, -1))
            for raw in items:
                if isinstance(raw, (bytes, bytearray)) and raw.startswith(task_id.encode()):
                    # remove from dead list and push back to main queue
                    await maybe_await(self.client.lrem(dead_key, 1, raw))  # type: ignore[arg-type]
                    await maybe_await(self.client.rpush(f"queue:{q}", raw))
                    return True

        return False

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task from pending, processing, or dead lists.

        Returns True if removed from any list.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queues = await self.get_all_queue_names()

        for q in queues:
            removed = 0
            for key_suffix in ("", ":processing", ":dead"):
                key = f"queue:{q}{key_suffix}"
                # lrem requires the exact member bytes - we'll remove by prefix match
                items = await maybe_await(self.client.lrange(key, 0, -1))
                for raw in items:
                    if isinstance(raw, (bytes, bytearray)) and raw.startswith(task_id.encode()):
                        await maybe_await(self.client.lrem(key, 1, raw))  # type: ignore[arg-type]
                        removed += 1
            if removed > 0:
                return True

        return False

    async def get_worker_stats(self) -> list[WorkerInfo]:
        """Return worker heartbeats stored in `workers:{id}` hashes.

        Best-effort: scans keys `worker:*` and builds WorkerInfo objects.
        """
        # WorkerInfo and datetime imported at module level
        if self.client is None:
            await self.connect()
            assert self.client is not None

        workers: list[WorkerInfo] = []
        cur = 0
        while True:
            cur, keys = await maybe_await(self.client.scan(cur, match="worker:*"))
            for k in keys:
                if isinstance(k, bytes):
                    k = k.decode()
                worker_id = k.split(":", 1)[1]
                data = await maybe_await(self.client.hgetall(k))
                status = (
                    (data.get(b"status") or data.get("status") or b"idle").decode()
                    if data
                    else "idle"
                )
                last_hb = None
                if data:
                    ts = data.get(b"last_heartbeat") or data.get("last_heartbeat")
                    try:
                        last_hb = datetime.fromtimestamp(float(ts), UTC) if ts else None
                    except Exception:
                        last_hb = None

                workers.append(
                    WorkerInfo(
                        worker_id=worker_id,
                        status=status,
                        current_task_id=None,
                        tasks_processed=int(
                            data.get(b"tasks_processed") or data.get("tasks_processed") or 0
                        ),
                        uptime_seconds=int(
                            data.get(b"uptime_seconds") or data.get("uptime_seconds") or 0
                        ),
                        last_heartbeat=last_hb,
                    )
                )
            if cur == 0:
                break

        return workers
