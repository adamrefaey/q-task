from abc import ABC, abstractmethod


class BaseDriver(ABC):
    """Protocol that all queue drivers must implement.

    Defines the contract for queue operations that enable task enqueueing,
    dequeueing, acknowledgment, and queue inspection. Drivers can implement
    delays differently based on their underlying technology.
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
