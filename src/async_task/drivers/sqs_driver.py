from base64 import b64decode, b64encode
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from aioboto3 import Session
from types_aiobotocore_sqs import SQSClient

from .base_driver import BaseDriver


@dataclass
class SQSDriver(BaseDriver):
    """AWS SQS-based queue driver for distributed task processing.

    IMPLEMENTATION DETAILS:
    ======================

    Message Encoding:
    - Task data Base64-encoded (SQS requires UTF-8 text)
    - Queue URLs cached for performance
    - Auto-creates queues with best-practice settings (long polling, 14-day retention)

    Delay Support:
    - Native SQS DelaySeconds (max 900s/15min)
    - Server-side, persistent across restarts
    - For longer delays: Use EventBridge Scheduler or Step Functions

    Receipt Handle Abstraction:
    - SQS receipt handles stored in _receipt_handles dict (keyed by task_data)
    - Maintains BaseDriver protocol: dequeue() returns bytes, not receipt handle
    - ack/nack retrieve handle from cache using task_data as key
    - Handles cleaned up after ack/nack or on disconnect

    Session Management:
    - Uses AsyncExitStack for proper aioboto3 client lifecycle
    - DO NOT call __aenter__/__aexit__ directly
    - Pattern: _exit_stack.enter_async_context(session.client('sqs'))

    Thread Safety:
    - Not thread-safe: Use separate driver instance per worker
    - Async-safe: Compatible with asyncio.gather()
    """

    region_name: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    queue_url_prefix: str | None = None
    visibility_timeout: int = 300
    session: Session | None = field(default=None, init=False, repr=False)
    client: SQSClient | None = field(default=None, init=False, repr=False)
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _queue_urls: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _receipt_handles: dict[bytes, str] = field(default_factory=dict, init=False, repr=False)

    async def connect(self) -> None:
        """Establish connection to AWS SQS.

        Uses AsyncExitStack to manage client lifecycle properly.
        Idempotent - safe to call multiple times.

        Raises:
            ClientError: If credentials invalid or insufficient permissions
        """

        if self.client is not None:
            return

        self.session = Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region_name,
        )

        # Use AsyncExitStack to properly manage client context manager lifecycle
        # This is the recommended pattern per aioboto3 docs for long-lived clients
        self._exit_stack = AsyncExitStack()
        self.client = await self._exit_stack.enter_async_context(self.session.client("sqs"))

    async def disconnect(self) -> None:
        """Close connection and cleanup resources.

        Clears queue URL cache and receipt handle cache.
        Idempotent - safe to call multiple times.
        """

        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None

        self.client = None
        self.session = None
        self._queue_urls.clear()
        self._receipt_handles.clear()

    async def enqueue(self, queue_name: str, task_data: bytes, delay_seconds: int = 0) -> None:
        """Add task to queue with optional delay.

        Base64-encodes task_data before sending. Auto-creates queue if needed.

        Args:
            queue_name: Queue name (auto-created if not exists)
            task_data: Serialized task data (will be Base64-encoded)
            delay_seconds: Delay in seconds (0-900 max, SQS limit)

        Raises:
            ValueError: If delay_seconds > 900
            ClientError: If AWS API call fails
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        if delay_seconds > 900:
            raise ValueError(
                f"SQS delay_seconds cannot exceed 900 (15 minutes), got {delay_seconds}. "
                f"For longer delays, use EventBridge Scheduler or Step Functions."
            )

        queue_url = await self._get_queue_url(queue_name)
        message_body = b64encode(task_data).decode("ascii")

        params: dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": message_body}

        if delay_seconds > 0:
            params["DelaySeconds"] = delay_seconds

        await self.client.send_message(**params)

    async def dequeue(self, queue_name: str, timeout: int = 0) -> bytes | None:
        """Retrieve task from queue.

        Returns task_data only (BaseDriver protocol). SQS receipt handle stored
        internally in _receipt_handles[task_data] for later ack/nack.

        Args:
            queue_name: Queue name
            timeout: Max seconds to wait (0-20, capped at 20)

        Returns:
            Decoded task data (bytes) or None if no messages

        Note:
            Message becomes invisible to other consumers for visibility_timeout.
            Receipt handle cached for ack/nack using task_data as key.
        """

        if self.client is None:
            await self.connect()
            assert self.client is not None

        queue_url = await self._get_queue_url(queue_name)
        response = await self.client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=min(timeout, 20),
            MessageAttributeNames=["All"],
        )

        messages = response.get("Messages", [])
        if not messages:
            return None

        message = messages[0]
        body = message.get("Body")
        receipt_handle = message.get("ReceiptHandle")

        if body is None or receipt_handle is None:
            return None

        task_data = b64decode(body)

        # Store receipt handle keyed by task_data for later ack/nack
        # This maintains protocol compatibility (returning only bytes)
        # while preserving SQS-specific receipt handle for operations
        self._receipt_handles[task_data] = receipt_handle

        return task_data

    async def ack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Acknowledge successful task processing.

        Deletes message from queue. Receipt handle is task_data from dequeue(),
        used to retrieve actual SQS receipt handle from cache.

        Args:
            queue_name: Queue name
            receipt_handle: Task data (as bytes) from dequeue()

        Note:
            Idempotent - safe to call multiple times.
            Cleans up receipt handle from cache.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        # Retrieve actual SQS receipt handle from cache
        sqs_receipt_handle = self._receipt_handles.get(receipt_handle)

        if sqs_receipt_handle is None:
            # Receipt handle not found - message may have been already ack'd or timed out
            # This is not an error - ack is idempotent
            return

        queue_url = await self._get_queue_url(queue_name)
        await self.client.delete_message(QueueUrl=queue_url, ReceiptHandle=sqs_receipt_handle)

        # Clean up receipt handle from cache
        self._receipt_handles.pop(receipt_handle, None)

    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject task and make immediately available for reprocessing.

        Sets visibility timeout to 0. Receipt handle is task_data from dequeue(),
        used to retrieve actual SQS receipt handle from cache.

        Args:
            queue_name: Queue name
            receipt_handle: Task data (as bytes) from dequeue()

        Note:
            Idempotent - safe to call multiple times.
            Cleans up receipt handle from cache.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        # Retrieve actual SQS receipt handle from cache
        sqs_receipt_handle = self._receipt_handles.get(receipt_handle)

        if sqs_receipt_handle is None:
            # Receipt handle not found - message may have been already processed or timed out
            # This is not an error - nack is idempotent
            return

        queue_url = await self._get_queue_url(queue_name)
        await self.client.change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=sqs_receipt_handle,
            VisibilityTimeout=0,  # Make immediately visible
        )

        # Clean up receipt handle from cache (it will get new handle on next receive)
        self._receipt_handles.pop(receipt_handle, None)

    async def get_queue_size(self, queue_name: str) -> int:
        """Get approximate number of visible messages in queue.

        Args:
            queue_name: Queue name

        Returns:
            Approximate count (excludes in-flight and delayed messages)

        Note:
            APPROXIMATE only - may lag by a few seconds due to distributed nature.
            Good for monitoring, not for strict guarantees.
        """
        if self.client is None:
            await self.connect()
            assert self.client is not None

        queue_url = await self._get_queue_url(queue_name)
        response = await self.client.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"]
        )

        attributes = response.get("Attributes")
        if not attributes:
            return 0

        count = attributes.get("ApproximateNumberOfMessages")
        return int(count) if count is not None else 0

    async def _get_queue_url(self, queue_name: str) -> str:
        """Get queue URL with caching.

        Checks cache first. If queue_url_prefix set, constructs URL directly.
        Otherwise calls get_queue_url API.

        Args:
            queue_name: Queue name

        Returns:
            Queue URL (cached for subsequent calls)

        Raises:
            QueueDoesNotExist: If queue doesn't exist
        """

        if queue_name in self._queue_urls:
            return self._queue_urls[queue_name]

        assert self.client is not None

        queue_url: str
        if self.queue_url_prefix:
            # Fast path: Construct URL directly (no API call)
            queue_url = f"{self.queue_url_prefix.rstrip('/')}/{queue_name}"
        else:
            # Slow path: Call AWS API to get queue URL
            response = await self.client.get_queue_url(QueueName=queue_name)
            queue_url = response["QueueUrl"]

        self._queue_urls[queue_name] = queue_url
        return queue_url
