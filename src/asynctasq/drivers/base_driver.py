from abc import ABC, abstractmethod
from typing import Any


class BaseDriver(ABC):
    """Protocol that all queue drivers must implement.

    Defines the contract for queue operations that enable task enqueueing,
    dequeueing, acknowledgment, and queue inspection. Drivers can implement
    delays differently based on their underlying technology.

    Note:
        Monitoring methods yield raw data (dicts/tuples) rather than models.
        Use MonitoringService to convert raw data to typed models.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the queue backend.

        Should be called once at application startup or before first use.
        May create connection pools, authenticate, or initialize resources.

        Raises:
            ConnectionError: If connection cannot be established
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the queue backend.

        Should be called during application shutdown to clean up resources.
        Must be idempotent - safe to call multiple times.
        """
        ...

    @abstractmethod
    async def enqueue(self, queue_name: str, task_data: bytes, delay_seconds: int = 0) -> None:
        """Add a task to the queue.

        Args:
            queue_name: Name of the queue
            task_data: Serialized task data (msgpack bytes)
            delay_seconds: Optional delay before task becomes visible (default: 0)

        Raises:
            ValueError: If delay_seconds exceeds driver limits
            ConnectionError: If not connected to backend

        Note:
            Delay implementation is driver-specific
        """
        ...

    @abstractmethod
    async def dequeue(self, queue_name: str, poll_seconds: int = 0) -> bytes | None:
        """Retrieve a task from the queue.

        Args:
            queue_name: Name of the queue
            poll_seconds: How long to poll for a task in seconds (0 = non-blocking)

        Returns:
            Serialized task data or None if no tasks available

        Raises:
            ConnectionError: If not connected to backend

        Note:
            - poll_seconds=0: Non-blocking, returns immediately
            - poll_seconds>0: Polls up to poll_seconds seconds waiting for task
            - For delayed tasks, only returns tasks past their delay time
        """
        ...

    @abstractmethod
    async def ack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Acknowledge successful processing of a task.

        Args:
            queue_name: Name of the queue
            receipt_handle: Driver-specific identifier for the message

        Raises:
            ValueError: If receipt_handle is invalid or expired

        Note:
            After ack, the task is permanently removed from the queue.
            Some drivers (Redis) may not require explicit ack.
        """
        ...

    @abstractmethod
    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject a task, making it available for reprocessing.

        Args:
            queue_name: Name of the queue
            receipt_handle: Driver-specific identifier for the message

        Raises:
            ValueError: If receipt_handle is invalid or expired

        Note:
            After nack, the task becomes visible again for other workers.
            Used for retry logic when task processing fails.
        """
        ...

    @abstractmethod
    async def get_queue_size(
        self,
        queue_name: str,
        include_delayed: bool,
        include_in_flight: bool,
    ) -> int:
        """Get approximate number of tasks in queue.

        Args:
            queue_name: Name of the queue
            include_delayed: Include delayed tasks in count
            include_in_flight: Include in-flight/processing tasks in count

        Returns:
            Approximate count of tasks based on parameters:
            - Both False: Only visible/ready tasks
            - include_delayed=True: Ready + delayed tasks
            - include_in_flight=True: Ready + in-flight tasks
            - Both True: Ready + delayed + in-flight tasks

        Note:
            Result may be approximate for distributed systems (e.g., SQS).
            Should not be used for strict guarantees.

            Driver limitations:
            - Redis: Exact counts for ready/delayed, in-flight not tracked (always 0)
            - PostgreSQL/MySQL: Exact counts for all categories
            - SQS: Approximate counts for all categories
        """
        ...

    @abstractmethod
    async def get_queue_stats(self, queue: str) -> dict[str, Any]:
        """
        Get real-time statistics for a specific queue.

        Args:
            queue: Queue name

        Returns:
            Dict with keys: name, depth, processing, completed_total, failed_total,
            avg_duration_ms (optional), throughput_per_minute (optional)

        Implementation Notes:
            - Redis: Use LLEN for depth, ZCARD for processing, counters for totals
            - PostgreSQL: COUNT queries with status filters
            - MySQL: Similar to PostgreSQL
            - RabbitMQ: Use management API /api/queues/{vhost}/{name}
            - SQS: Use GetQueueAttributes API
        """
        pass

    @abstractmethod
    async def get_all_queue_names(self) -> list[str]:
        """
        Get list of all queue names.

        Returns:
            List of queue names

        Implementation Notes:
            - Redis: KEYS queue:* (or SCAN for production)
            - PostgreSQL: SELECT DISTINCT queue FROM tasks
            - MySQL: Similar to PostgreSQL
            - RabbitMQ: GET /api/queues
            - SQS: ListQueues API
        """
        pass

    @abstractmethod
    async def get_global_stats(self) -> dict[str, int]:
        """
        Get global task statistics across all queues.

        Returns:
            Dictionary with keys: pending, running, completed, failed, total

        Example:
            {
                "pending": 150,
                "running": 5,
                "completed": 10243,
                "failed": 87,
                "total": 10485
            }

        Implementation Notes:
            - Use efficient aggregation queries
            - Cache results for 5 seconds to reduce load
            - Consider using Redis counters for real-time stats
        """
        pass

    @abstractmethod
    async def get_running_tasks(self, limit: int = 50, offset: int = 0) -> list[tuple[bytes, str]]:
        """
        Get currently running tasks with pagination.

        Args:
            limit: Maximum tasks to return (default: 50, max: 500)
            offset: Pagination offset

        Returns:
            List of (raw_bytes, queue_name) tuples for running tasks

        Implementation Notes:
            - Order by started_at DESC (newest first)
            - Redis: Query processing lists
            - PostgreSQL/MySQL: WHERE status='running' ORDER BY started_at DESC
            - RabbitMQ: Track in separate Redis/DB (AMQP doesn't expose running tasks)
            - SQS: Similar to RabbitMQ (use visibility timeout tracking)
        """
        pass

    @abstractmethod
    async def get_tasks(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[bytes, str, str]], int]:
        """
        Get raw serialized task data with queue name and status.

        Returns raw bytes as stored in the queue, along with queue name
        and inferred status. Callers are responsible for deserialization.

        Args:
            status: Filter by status (pending, running)
            queue: Filter by queue name
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            Tuple of (list of (raw_bytes, queue_name, status), total_count)

        Note:
            The raw bytes are msgpack-serialized task dicts. Consumers
            should use a serializer to deserialize them.
        """
        pass

    @abstractmethod
    async def get_task_by_id(self, task_id: str) -> bytes | None:
        """
        Get raw serialized task data by ID.

        Args:
            task_id: Task UUID

        Returns:
            Raw msgpack bytes or None if not found

        Implementation Notes:
            - Use primary key lookup (fast)
            - Caller is responsible for deserialization
        """
        pass

    @abstractmethod
    async def retry_task(self, task_id: str) -> bool:
        """
        Retry a failed task by re-enqueueing it.

        Args:
            task_id: Task UUID to retry

        Returns:
            True if successfully re-enqueued, False otherwise

        Implementation Notes:
            - Use primary key lookup for efficient retry (Postgres/MySQL)
            - For drivers without ID-based indexing (Redis), return False
              and let TaskService handle via retry_raw_task + scanning
            - Only allow retry if status is FAILED or in dead-letter queue
            - Reset status back to PENDING
        """
        pass

    async def retry_raw_task(self, queue_name: str, raw_bytes: bytes) -> bool:
        """
        Retry a task by its raw serialized bytes.

        This is a primitive operation for drivers that cannot efficiently
        lookup tasks by ID (like Redis). TaskService uses this after
        finding the task via scanning and deserialization.

        The operation should:
        1. Remove the task from dead/failed lists
        2. Re-enqueue to the main queue

        Args:
            queue_name: Name of the queue containing the task
            raw_bytes: The exact raw bytes of the task to retry

        Returns:
            True if retried, False if not found

        Note:
            Default implementation returns False. Override in drivers
            that support raw bytes operations (e.g., Redis).
        """
        return False

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task from queue/history by ID.

        Args:
            task_id: Task UUID to delete

        Returns:
            True if deleted, False if not found

        Implementation Notes:
            - Use primary key lookup for efficient deletion (Postgres/MySQL)
            - For drivers without ID-based indexing (Redis), return False
              and let TaskService handle via delete_raw_task + scanning
            - Remove from queue if pending
            - Don't allow deleting running tasks (return False)
        """
        pass

    async def delete_raw_task(self, queue_name: str, raw_bytes: bytes) -> bool:
        """
        Delete a task by its raw serialized bytes.

        This is a primitive operation for drivers that cannot efficiently
        lookup tasks by ID (like Redis). TaskService uses this after
        finding the task via scanning and deserialization.

        Args:
            queue_name: Name of the queue containing the task
            raw_bytes: The exact raw bytes of the task to delete

        Returns:
            True if deleted, False if not found

        Note:
            Default implementation returns False. Override in drivers
            that support raw bytes deletion (e.g., Redis with LREM).
        """
        return False

    @abstractmethod
    async def get_worker_stats(self) -> list[dict[str, Any]]:
        """
        Get statistics for all active workers.

        Returns:
            List of dicts with keys: worker_id, status, current_task_id (optional),
            tasks_processed, uptime_seconds, last_heartbeat (ISO string or None),
            load_percentage

        Implementation Notes:
            - Workers send heartbeat every 30 seconds
            - Mark as 'down' if no heartbeat for 2 minutes
            - Track current task via worker registry (Redis hash or DB table)
            - Calculate load from worker metrics (if available)
        """
        pass
