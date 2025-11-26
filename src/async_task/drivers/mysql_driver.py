import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from asyncmy import Pool, create_pool

from .base_driver import BaseDriver


@dataclass
class MySQLDriver(BaseDriver):
    """MySQL-based queue driver with transactional dequeue and dead-letter support.

    Architecture:
        - Tasks stored in configurable table (default: task_queue)
        - Dead-letter table for failed tasks (default: dead_letter_queue)
        - Transactional dequeue using SELECT ... FOR UPDATE SKIP LOCKED
        - BLOB payload storage for binary data
        - DATETIME for delay calculations
        - Visibility timeout to handle worker crashes

    Features:
        - Concurrent workers with SKIP LOCKED
        - Dead-letter queue for failed tasks
        - Configurable retry logic with exponential backoff
        - Visibility timeout for crash recovery
        - Connection pooling with asyncmy
        - Auto-recovery of stuck tasks via poll loop

    Requirements:
        - MySQL 8.0+ (SKIP LOCKED support)
        - InnoDB storage engine (for row-level locking)
        - asyncmy library
    """

    dsn: str = "mysql://user:pass@localhost:3306/dbname"
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
        """Initialize asyncmy connection pool with configurable size."""
        if self.pool is None:
            self.pool = await create_pool(
                host=self._parse_host(),
                port=self._parse_port(),
                user=self._parse_user(),
                password=self._parse_password(),
                db=self._parse_database(),
                minsize=self.min_pool_size,
                maxsize=self.max_pool_size,
            )

    async def disconnect(self) -> None:
        """Close connection pool and cleanup."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
        self._receipt_handles.clear()

    def _parse_host(self) -> str:
        """Parse host from DSN."""
        # Parse mysql://user:pass@host:port/dbname
        if "://" in self.dsn:
            part = self.dsn.split("://")[1]
            if "@" in part:
                part = part.split("@")[1]
            if ":" in part:
                return part.split(":")[0]
            if "/" in part:
                return part.split("/")[0]
            return part
        return "localhost"

    def _parse_port(self) -> int:
        """Parse port from DSN."""
        if "://" in self.dsn:
            part = self.dsn.split("://")[1]
            if "@" in part:
                part = part.split("@")[1]
            if ":" in part and "/" in part:
                port_str = part.split(":")[1].split("/")[0]
                return int(port_str)
        return 3306

    def _parse_user(self) -> str:
        """Parse user from DSN."""
        if "://" in self.dsn:
            part = self.dsn.split("://")[1]
            if "@" in part:
                user_part = part.split("@")[0]
                if ":" in user_part:
                    return user_part.split(":")[0]
                return user_part
        return "root"

    def _parse_password(self) -> str:
        """Parse password from DSN."""
        if "://" in self.dsn:
            part = self.dsn.split("://")[1]
            if "@" in part:
                user_part = part.split("@")[0]
                if ":" in user_part:
                    return user_part.split(":")[1]
        return ""

    def _parse_database(self) -> str:
        """Parse database name from DSN."""
        if "://" in self.dsn:
            part = self.dsn.split("://")[1]
            if "/" in part:
                return part.split("/")[1].split("?")[0]
        return "test_db"

    async def init_schema(self) -> None:
        """Initialize database schema for queue and dead-letter tables.

        Creates tables if they don't exist. Safe to call multiple times (idempotent).
        Should be called once during application setup.

        Raises:
            asyncmy.Error: If table creation fails
        """
        if self.pool is None:
            await self.connect()
            assert self.pool is not None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Create queue table
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.queue_table} (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        queue_name VARCHAR(255) NOT NULL,
                        payload BLOB NOT NULL,
                        available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                        locked_until DATETIME(6) NULL,
                        status VARCHAR(50) NOT NULL DEFAULT 'pending',
                        attempts INT NOT NULL DEFAULT 0,
                        max_attempts INT NOT NULL DEFAULT 3,
                        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
                        INDEX idx_{self.queue_table}_lookup (queue_name, status, available_at, locked_until)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

                # Create dead-letter table
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.dead_letter_table} (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        queue_name VARCHAR(255) NOT NULL,
                        payload BLOB NOT NULL,
                        attempts INT NOT NULL,
                        error_message TEXT,
                        failed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
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
            VALUES (%s, %s, DATE_ADD(NOW(6), INTERVAL %s SECOND), 'pending', 0, %s, NOW(6))
        """
        async with self.pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        query, (queue_name, task_data, delay_seconds, self.max_attempts)
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

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
                WHERE queue_name = %s
                  AND status = 'pending'
                  AND available_at <= NOW(6)
                  AND (locked_until IS NULL OR locked_until < NOW(6))
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """

            async with self.pool.acquire() as conn:
                await conn.begin()
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(query, (queue_name,))
                        row = await cursor.fetchone()

                        if row:
                            task_id = row[0]

                            # Update status and set visibility timeout
                            await cursor.execute(
                                f"""
                                UPDATE {self.queue_table}
                                SET status = 'processing',
                                    locked_until = DATE_ADD(NOW(6), INTERVAL %s SECOND),
                                    updated_at = NOW(6)
                                WHERE id = %s
                                """,
                                (self.visibility_timeout_seconds, task_id),
                            )

                            # Generate unique receipt handle
                            receipt_handle = uuid4().bytes
                            self._receipt_handles[receipt_handle] = task_id

                            await conn.commit()
                            return receipt_handle
                        else:
                            await conn.rollback()
                except Exception:
                    await conn.rollback()
                    raise

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
            async with self.pool.acquire() as conn:
                await conn.begin()
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            f"DELETE FROM {self.queue_table} WHERE id = %s", (task_id,)
                        )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
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
            await conn.begin()
            try:
                async with conn.cursor() as cursor:
                    # Get current attempts
                    await cursor.execute(
                        f"SELECT attempts, max_attempts, queue_name, payload FROM {self.queue_table} WHERE id = %s",
                        (task_id,),
                    )
                    row = await cursor.fetchone()

                    if row:
                        attempts = row[0] + 1
                        max_attempts = row[1]
                        task_queue_name = row[2]
                        payload = row[3]

                        if attempts < max_attempts:
                            # Retry: update attempts, available_at, and clear lock
                            retry_delay = self.retry_delay_seconds * (
                                2 ** (attempts - 1)
                            )  # Exponential backoff
                            await cursor.execute(
                                f"""
                                UPDATE {self.queue_table}
                                SET attempts = %s,
                                    available_at = DATE_ADD(NOW(6), INTERVAL %s SECOND),
                                    status = 'pending',
                                    locked_until = NULL,
                                    updated_at = NOW(6)
                                WHERE id = %s
                                """,
                                (attempts, retry_delay, task_id),
                            )
                        else:
                            # Move to dead letter queue
                            await cursor.execute(
                                f"""
                                INSERT INTO {self.dead_letter_table}
                                    (queue_name, payload, attempts, error_message, failed_at)
                                VALUES (%s, %s, %s, 'Max retries exceeded', NOW(6))
                                """,
                                (task_queue_name, payload, attempts),
                            )
                            await cursor.execute(
                                f"DELETE FROM {self.queue_table} WHERE id = %s", (task_id,)
                            )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

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
        conditions = ["queue_name = %s"]

        if include_delayed and include_in_flight:
            # All tasks: pending (ready + delayed) + processing
            conditions.append("(status = 'pending' OR status = 'processing')")
        elif include_delayed:
            # All pending tasks (ready + delayed), not locked
            conditions.append("status = 'pending'")
        elif include_in_flight:
            # Ready tasks + processing
            conditions.append(
                "((status = 'pending' AND available_at <= NOW(6) AND (locked_until IS NULL OR locked_until < NOW(6))) OR status = 'processing')"
            )
        else:
            # Only ready tasks (pending, available, not locked)
            conditions.append("status = 'pending'")
            conditions.append("available_at <= NOW(6)")
            conditions.append("(locked_until IS NULL OR locked_until < NOW(6))")

        where_clause = " AND ".join(conditions)
        query = f"SELECT COUNT(*) FROM {self.queue_table} WHERE {where_clause}"

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (queue_name,))
                row = await cursor.fetchone()
                return row[0] if row else 0
