import asyncio
from collections import deque
from dataclasses import dataclass, field

from .base_driver import BaseDriver


@dataclass
class MemoryDriver(BaseDriver):
    """In-memory queue driver for testing and development.

    Architecture:
        - Main queues: deques (FIFO, O(1) operations)
        - Delayed tasks: list of (target_time, task_data) tuples
        - Background task: 100ms polling for ready delayed tasks
        - Receipt handle: task_data itself (simplest approach)

    Performance:
        - Latency: < 0.1ms | Throughput: 50k+ tasks/sec | Delay precision: ~100ms

    Use Cases:
        ✓ Unit/integration tests | ✓ Local dev | ✓ CI/CD | ✗ Production

    Limitations:
        - No persistence | Single-process only | No visibility timeout
    """

    _queues: dict[str, deque[bytes]] = field(default_factory=dict, init=False, repr=False)
    # Example: {"default": [(timestamp, task_data), (1234567895.2, b"task2")]}
    # Access tuple: _delayed_tasks["queue_name"][0] -> (float, bytes)
    _delayed_tasks: dict[str, list[tuple[float, bytes]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _processing: dict[bytes, str] = field(default_factory=dict, init=False, repr=False)
    _background_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)

    async def connect(self) -> None:
        """Initialize queues and start background processor (100ms polling).

        Idempotent - safe to call multiple times.
        """

        if self._connected:
            return

        self._queues = {}
        self._delayed_tasks = {}
        self._processing = {}
        self._background_task = asyncio.create_task(
            self._process_delayed_tasks_loop(), name="memory_driver_delayed_processor"
        )
        self._connected = True

    async def disconnect(self) -> None:
        """Stop background processor and clear all data.

        Idempotent - safe to call multiple times.
        """

        if not self._connected:
            return

        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

        self._queues.clear()
        self._delayed_tasks.clear()
        self._processing.clear()
        self._background_task = None
        self._connected = False

    async def enqueue(self, queue_name: str, task_data: bytes, delay_seconds: int = 0) -> None:
        """Add task to queue.

        Args:
            queue_name: Queue identifier (auto-created)
            task_data: Serialized task bytes
            delay_seconds: Delay before task becomes visible (0 = immediate)

        Implementation:
            - Immediate: append to deque (O(1))
            - Delayed: add to sorted list, background task moves when ready
        """

        if not self._connected:
            await self.connect()

        if delay_seconds <= 0:
            if queue_name not in self._queues:
                self._queues[queue_name] = deque()
            self._queues[queue_name].append(task_data)
        else:
            if queue_name not in self._delayed_tasks:
                self._delayed_tasks[queue_name] = []

            loop = asyncio.get_running_loop()
            target_time = loop.time() + delay_seconds

            self._delayed_tasks[queue_name].append((target_time, task_data))
            self._delayed_tasks[queue_name].sort(key=lambda item: item[0])

    async def dequeue(self, queue_name: str, timeout: int = 0) -> bytes | None:
        """Retrieve task from queue.

        Args:
            queue_name: Queue to dequeue from
            timeout: Seconds to wait (0 = non-blocking)

        Returns:
            Task data or None if timeout expires

        Note:
            Polls every 100ms if timeout > 0. Task tracked in _processing until ack/nack.
        """

        if not self._connected:
            await self.connect()

        if queue_name not in self._queues:
            self._queues[queue_name] = deque()

        queue = self._queues[queue_name]

        # Try immediate dequeue
        if queue:
            task_data = queue.popleft()
            self._processing[task_data] = queue_name

            return task_data

        # Poll if timeout specified (100ms interval)
        if timeout > 0:
            loop = asyncio.get_running_loop()
            start_time = loop.time()
            deadline = start_time + timeout

            while loop.time() < deadline:
                await asyncio.sleep(0.1)

                if queue:
                    task_data = queue.popleft()
                    self._processing[task_data] = queue_name

                    return task_data

        return None

    async def ack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Acknowledge successful completion (remove from in-flight tracking)."""

        if not self._connected:
            await self.connect()

        self._processing.pop(receipt_handle, None)

    async def nack(self, queue_name: str, receipt_handle: bytes) -> None:
        """Reject task and re-insert at front for immediate retry."""

        if not self._connected:
            await self.connect()

        self._processing.pop(receipt_handle, None)

        if queue_name not in self._queues:
            self._queues[queue_name] = deque()

        self._queues[queue_name].appendleft(receipt_handle)

    async def get_queue_size(self, queue_name: str) -> int:
        """Get exact count of tasks in queue (excludes in-flight and delayed)."""

        if not self._connected:
            await self.connect()

        return len(self._queues.get(queue_name, deque()))

    async def _process_delayed_tasks_loop(self) -> None:
        """Background task: move ready delayed tasks to main queue every 100ms."""

        try:
            while True:
                await asyncio.sleep(0.1)
                await self._process_delayed_tasks()
        except asyncio.CancelledError:
            pass

    async def _process_delayed_tasks(self) -> None:
        """Move tasks with target_time <= now to main queues."""

        loop = asyncio.get_running_loop()
        current_time = loop.time()

        for queue_name, delayed_tasks in list(self._delayed_tasks.items()):
            ready_tasks = []
            remaining_tasks = []

            for target_time, task_data in delayed_tasks:
                if target_time <= current_time:
                    ready_tasks.append(task_data)
                else:
                    remaining_tasks.append((target_time, task_data))

            if remaining_tasks:
                self._delayed_tasks[queue_name] = remaining_tasks
            else:
                self._delayed_tasks.pop(queue_name, None)

            if ready_tasks:
                if queue_name not in self._queues:
                    self._queues[queue_name] = deque()

                self._queues[queue_name].extend(ready_tasks)
