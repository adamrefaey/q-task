"""SyncProcessTask for sync CPU-bound tasks via ProcessPoolExecutor."""

from __future__ import annotations

from abc import abstractmethod

from asynctasq.tasks.core.base_task import BaseTask
from asynctasq.tasks.utils.execution_helpers import execute_in_process_sync


class SyncProcessTask[T](BaseTask[T]):
    """Sync CPU-bound task via ProcessPoolExecutor (computation, data processing, ML, crypto).

    Bypasses GIL by running in separate process. For I/O-bound work, use AsyncTask or SyncTask.
    """

    async def run(self) -> T:
        """Execute task via ProcessPoolExecutor."""
        return await execute_in_process_sync(self.execute)

    @abstractmethod
    def execute(self) -> T:
        """Execute sync CPU-bound logic (user implementation, runs in subprocess).

        Note:
            Arguments and return value must be serializable (msgpack-compatible).
        """
        ...
