"""SyncTask for sync I/O-bound tasks via ThreadPoolExecutor."""

from __future__ import annotations

from abc import abstractmethod

from asynctasq.tasks.core.base_task import BaseTask
from asynctasq.tasks.utils.execution_helpers import execute_in_thread


class SyncTask[T](BaseTask[T]):
    """Sync I/O-bound task via ThreadPoolExecutor (requests, file I/O, sync DB drivers).

    Runs sync execute() in thread pool to avoid blocking event loop.
    For CPU-bound work, use SyncProcessTask.
    """

    async def run(self) -> T:
        """Execute task via ThreadPoolExecutor."""
        return await execute_in_thread(self.execute)

    @abstractmethod
    def execute(self) -> T:
        """Execute sync I/O-bound logic (user implementation, runs in thread pool)."""
        ...
