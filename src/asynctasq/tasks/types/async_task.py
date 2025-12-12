"""AsyncTask for async I/O-bound tasks."""

from __future__ import annotations

from abc import abstractmethod

from asynctasq.tasks.core.base_task import BaseTask


class AsyncTask[T](BaseTask[T]):
    """Async I/O-bound task (DB queries, HTTP calls, file I/O).

    Implement async execute() with business logic. For CPU-bound work, use AsyncProcessTask.
    """

    async def run(self) -> T:
        """Execute task by calling execute() directly."""
        return await self.execute()

    @abstractmethod
    async def execute(self) -> T:
        """Execute async I/O-bound logic (user implementation)."""
        ...
