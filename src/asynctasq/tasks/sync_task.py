# Sync task support
from abc import abstractmethod
import asyncio

from .base_task import BaseTask


class SyncTask[T](BaseTask[T]):
    """Synchronous task that will be run in thread pool."""

    @abstractmethod
    def handle_sync(self) -> T:
        """Synchronous handle method."""
        pass

    async def handle(self) -> T:
        """Wrap sync method in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.handle_sync)
