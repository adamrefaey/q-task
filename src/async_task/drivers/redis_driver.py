from dataclasses import dataclass, field
from time import time

from redis.asyncio import Redis

from .base_driver import BaseDriver


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
            await self.client.zadd(f"queue:{queue_name}:delayed", {task_data: process_at})  # type: ignore[misc]
        else:
            # LPUSH adds to left of list - workers RPOP from right (FIFO)
            await self.client.lpush(f"queue:{queue_name}", task_data)  # type: ignore[misc]

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
            result: bytes | None = await self.client.blmove(
                main_key, processing_key, poll_seconds, "RIGHT", "LEFT"
            )  # type: ignore[assignment]
            return result
        else:
            # LMOVE: non-blocking version
            return await self.client.lmove(main_key, processing_key, "RIGHT", "LEFT")  # type: ignore[return-value]

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
        # Remove task from processing list (LREM: count=1 removes first occurrence)
        await self.client.lrem(processing_key, 1, receipt_handle)  # type: ignore[misc]

    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject task and re-queue for immediate retry.

        Args:
            queue_name: Name of the queue
            receipt_handle: Task data from dequeue

        Implementation:
            Only requeues if task exists in processing list (prevents nack-after-ack).
            Uses LMOVE to atomically move from processing list back to main queue.
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        processing_key = f"queue:{queue_name}:processing"
        main_key = f"queue:{queue_name}"

        # Check if task is in processing list, then atomically move it back
        # Use pipeline to make it atomic: LREM (check+remove) then LPUSH (if found)
        async with self.client.pipeline(transaction=True) as pipe:
            # LREM returns count of removed items (0 if not found, 1 if found)
            pipe.lrem(processing_key, 1, receipt_handle)  # type: ignore[arg-type]
            pipe.lpush(main_key, receipt_handle)
            results = await pipe.execute()

            # If LREM returned 0, the task wasn't in processing, so remove it from main queue
            # This handles the nack-after-ack case
            if results[0] == 0:
                await self.client.lrem(main_key, 1, receipt_handle)  # type: ignore[misc]

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

        size: int = await self.client.llen(f"queue:{queue_name}")  # type: ignore[assignment]

        if include_delayed:
            delayed_size: int = await self.client.zcard(f"queue:{queue_name}:delayed")  # type: ignore[assignment]
            size += delayed_size

        if include_in_flight:
            processing_size: int = await self.client.llen(f"queue:{queue_name}:processing")  # type: ignore[assignment]
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
        ready_tasks: list[bytes] = await self.client.zrangebyscore(delayed_key, min=0, max=now)

        if ready_tasks:
            # Move tasks atomically: add to main queue and remove from delayed queue
            async with self.client.pipeline(transaction=True) as pipe:
                pipe.lpush(main_key, *ready_tasks)
                pipe.zremrangebyscore(delayed_key, 0, now)
                await pipe.execute()
