import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from asyncpg import Pool, create_pool

from .base_driver import BaseDriver


@dataclass
class PostgresDriver(BaseDriver):
    """PostgreSQL-based queue driver with transactional dequeue and dead-letter support.

    Architecture:
        - Tasks stored in configurable table (default: task_queue)
        - Dead-letter table for failed tasks (default: dead_letter_queue)
        - Transactional dequeue using SELECT ... FOR UPDATE SKIP LOCKED
        - BYTEA payload storage for binary data
        - TIMESTAMP for delay calculations
        - Visibility timeout to handle worker crashes

    Features:
        - Concurrent workers with SKIP LOCKED
        - Dead-letter queue for failed tasks
        - Configurable retry logic with exponential backoff
        - Visibility timeout for crash recovery
        - Connection pooling with asyncpg
        - Auto-recovery of stuck tasks via poll loop

    Requirements:
        - PostgreSQL 14+ (for SKIP LOCKED support and Django ORM integration)
        - asyncpg library
    """

    dsn: str = "postgresql://user:pass@localhost/dbname"
    queue_table: str = "task_queue"
    dead_letter_table: str = "dead_letter_queue"
    max_attempts: int = 3
    retry_delay_seconds: int = 60
    visibility_timeout_seconds: int = 300  # 5 minutes
    min_pool_size: int = 10
    max_pool_size: int = 10
    pool: Pool | None = field(default=None, init=False, repr=False)
    _receipt_handles: dict[bytes, int] = field(default_factory=dict, init=False, repr=False)

    async def connect(self) -> None:
        """Initialize asyncpg connection pool with configurable size."""
        if self.pool is None:
            self.pool = await create_pool(
                dsn=self.dsn,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )

    async def disconnect(self) -> None:
        """Close connection pool and cleanup."""
        if self.pool:
            await self.pool.close()
            self.pool = None
        self._receipt_handles.clear()

    async def init_schema(self) -> None:
        """Initialize database schema for queue and dead-letter tables.

        Creates tables if they don't exist. Safe to call multiple times (idempotent).
        Should be called once during application setup.

        Raises:
            asyncpg.PostgresError: If table creation fails
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        async with self.pool.acquire() as conn:
            # Create queue table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.queue_table} (
                    id SERIAL PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    payload BYTEA NOT NULL,
                    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    locked_until TIMESTAMPTZ,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Create index for efficient queue lookup
            # Composite index on queue_name, status, available_at, and locked_until
            # Note: We don't use a partial index with NOW() since NOW() is not IMMUTABLE
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.queue_table}_lookup
                ON {self.queue_table} (queue_name, status, available_at, locked_until)
            """)

            # Create dead-letter table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.dead_letter_table} (
                    id SERIAL PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    payload BYTEA NOT NULL,
                    attempts INTEGER NOT NULL,
                    error_message TEXT,
                    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

    async def enqueue(self, queue_name: str, task_data: bytes, delay_seconds: int = 0) -> None:
        """Add task to queue with optional delay.

        Args:
            queue_name: Name of the queue
            task_data: Serialized task data
            delay_seconds: Seconds to delay task visibility (0 = immediate)
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        query = f"""
            INSERT INTO {self.queue_table}
                (queue_name, payload, available_at, status, attempts, max_attempts, created_at)
            VALUES ($1, $2, NOW() + $3 * INTERVAL '1 second', 'pending', 0, $4, NOW())
        """
        await self.pool.execute(query, queue_name, task_data, delay_seconds, self.max_attempts)

    async def dequeue(self, queue_name: str, poll_seconds: int = 0) -> bytes | None:
        """Retrieve next available task with transactional locking and polling support.

        Args:
            queue_name: Name of the queue
            poll_seconds: Seconds to poll for task (0 = non-blocking)

        Returns:
            Unique receipt handle (UUID as bytes) or None if no tasks available

        Implementation:
            - Uses SELECT FOR UPDATE SKIP LOCKED for concurrent workers
            - Sets visibility timeout (locked_until) to prevent duplicate processing
            - Implements polling with 200ms interval if poll_seconds > 0
            - Auto-recovers stuck tasks (locked_until expired)
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        deadline = None
        if poll_seconds > 0:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + poll_seconds

        while True:
            # Select and lock a pending task
            query = f"""
                SELECT id, payload FROM {self.queue_table}
                WHERE queue_name = $1
                  AND status = 'pending'
                  AND available_at <= NOW()
                  AND (locked_until IS NULL OR locked_until < NOW())
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """

            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(query, queue_name)

                    if row:
                        task_id = row["id"]

                        # Update status and set visibility timeout
                        await conn.execute(
                            f"""
                            UPDATE {self.queue_table}
                            SET status = 'processing',
                                locked_until = NOW() + $1 * INTERVAL '1 second',
                                updated_at = NOW()
                            WHERE id = $2
                            """,
                            self.visibility_timeout_seconds,
                            task_id,
                        )

                        # Generate unique receipt handle
                        receipt_handle = uuid4().bytes
                        self._receipt_handles[receipt_handle] = task_id

                        return receipt_handle

            # No task found - check if we should poll
            if poll_seconds == 0:
                return None

            if deadline is not None:
                loop = asyncio.get_running_loop()
                if loop.time() >= deadline:
                    return None

                # Sleep for 200ms before next poll
                await asyncio.sleep(0.2)
            else:
                return None

    async def ack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Acknowledge successful processing and delete task.

        Args:
            queue_name: Name of the queue (unused but required by protocol)
            receipt_handle: Receipt handle from dequeue (UUID bytes)
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        task_id = self._receipt_handles.get(receipt_handle)
        if task_id:
            await self.pool.execute(f"DELETE FROM {self.queue_table} WHERE id = $1", task_id)
            self._receipt_handles.pop(receipt_handle, None)

    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject task for retry or move to dead letter queue.

        Args:
            queue_name: Name of the queue (unused but required by protocol)
            receipt_handle: Receipt handle from dequeue (UUID bytes)

        Implementation:
            - Increments attempt counter
            - If attempts < max_attempts: requeue with exponential backoff
            - If attempts >= max_attempts: move to dead letter queue
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        task_id = self._receipt_handles.get(receipt_handle)
        if not task_id:
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get current attempts
                row = await conn.fetchrow(
                    f"SELECT attempts, max_attempts, queue_name, payload FROM {self.queue_table} WHERE id = $1",
                    task_id,
                )

                if row:
                    attempts = row["attempts"] + 1
                    max_attempts = row["max_attempts"]
                    task_queue_name = row["queue_name"]
                    payload = row["payload"]

                    if attempts < max_attempts:
                        # Retry: update attempts, available_at, and clear lock
                        retry_delay = self.retry_delay_seconds * (
                            2 ** (attempts - 1)
                        )  # Exponential backoff
                        await conn.execute(
                            f"""
                            UPDATE {self.queue_table}
                            SET attempts = $1,
                                available_at = NOW() + $2 * INTERVAL '1 second',
                                status = 'pending',
                                locked_until = NULL,
                                updated_at = NOW()
                            WHERE id = $3
                            """,
                            attempts,
                            retry_delay,
                            task_id,
                        )
                    else:
                        # Move to dead letter queue
                        await conn.execute(
                            f"""
                            INSERT INTO {self.dead_letter_table}
                                (queue_name, payload, attempts, error_message, failed_at)
                            VALUES ($1, $2, $3, 'Max retries exceeded', NOW())
                            """,
                            task_queue_name,
                            payload,
                            attempts,
                        )
                        await conn.execute(f"DELETE FROM {self.queue_table} WHERE id = $1", task_id)

        self._receipt_handles.pop(receipt_handle, None)

    async def get_queue_size(
        self, queue_name: str, include_delayed: bool, include_in_flight: bool
    ) -> int:
        """Get number of tasks in queue based on parameters.

        Args:
            queue_name: Name of the queue
            include_delayed: Include delayed tasks (available_at > NOW())
            include_in_flight: Include in-flight/processing tasks

        Returns:
            Count of tasks based on the inclusion parameters:
            - Both False: Only ready tasks (pending, available_at <= NOW(), not locked)
            - include_delayed=True: Ready + delayed tasks
            - include_in_flight=True: Ready + in-flight tasks
            - Both True: Ready + delayed + in-flight tasks
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        # Build WHERE clause based on parameters
        conditions = ["queue_name = $1"]

        if include_delayed and include_in_flight:
            # All tasks: pending (ready + delayed) + processing
            conditions.append("(status = 'pending' OR status = 'processing')")
        elif include_delayed:
            # All pending tasks (ready + delayed), not locked
            conditions.append("status = 'pending'")
        elif include_in_flight:
            # Ready tasks + processing
            conditions.append(
                "((status = 'pending' AND available_at <= NOW() AND (locked_until IS NULL OR locked_until < NOW())) OR status = 'processing')"
            )
        else:
            # Only ready tasks (pending, available, not locked)
            conditions.append("status = 'pending'")
            conditions.append("available_at <= NOW()")
            conditions.append("(locked_until IS NULL OR locked_until < NOW())")

        where_clause = " AND ".join(conditions)
        query = f"SELECT COUNT(*) FROM {self.queue_table} WHERE {where_clause}"

        row = await self.pool.fetchrow(query, queue_name)
        return row["count"] if row else 0
