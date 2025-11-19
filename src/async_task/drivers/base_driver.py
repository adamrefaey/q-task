from abc import abstractmethod
from typing import Protocol


class BaseDriver(Protocol):
    """Protocol that all queue drivers must implement.

    Defines the contract for queue operations that enable task enqueueing,
    dequeueing, acknowledgment, and queue inspection. Drivers can implement
    delays differently based on their underlying technology.

    Delay Implementation Strategies:
        Each driver implements delays according to its capabilities:

        Redis:
            - In-memory sorted sets with timestamp scores
            - Library polls and moves ready tasks from delayed set to main queue
            - Supports sub-second precision
            - No external scheduler needed

        SQS:
            - Native DelaySeconds parameter
            - Queue engine handles delays server-side
            - Maximum 900 seconds (15 minutes)
            - No client polling required
            - More reliable (survives restarts)

        Memory:
            - In-memory list with (timestamp, data) tuples
            - Library polls on dequeue to check readiness
            - For testing/development only
            - Not persistent

    The unified enqueue(delay_seconds) interface abstracts these differences,
    allowing tasks to use delays without knowing the underlying implementation.

    Required Methods:
        - connect/disconnect: Lifecycle management
        - enqueue: Add task to queue (with optional delay)
        - dequeue: Retrieve task from queue (blocking or non-blocking)
        - ack: Acknowledge successful processing
        - nack: Reject task for reprocessing
        - get_queue_size: Inspect queue depth
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
            Delay implementation is driver-specific:
            - Redis: Sorted set with timestamp scores
            - SQS: Native DelaySeconds (max 900s)
            - Memory: In-memory timestamp tracking
        """
        ...

    @abstractmethod
    async def dequeue(self, queue_name: str, timeout: int = 0) -> bytes | None:
        """Retrieve a task from the queue.

        Args:
            queue_name: Name of the queue
            timeout: How long to wait for a task in seconds (0 = non-blocking)

        Returns:
            Serialized task data or None if no tasks available

        Raises:
            ConnectionError: If not connected to backend

        Note:
            - timeout=0: Non-blocking, returns immediately
            - timeout>0: Blocks up to timeout seconds waiting for task
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
    async def get_queue_size(self, queue_name: str) -> int:
        """Get approximate number of tasks in queue.

        Args:
            queue_name: Name of the queue

        Returns:
            Approximate count of visible tasks (excludes delayed/in-flight)

        Note:
            Result may be approximate for distributed systems (e.g., SQS).
            Should not be used for strict guarantees.
        """
        ...
