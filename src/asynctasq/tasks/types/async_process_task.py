"""AsyncProcessTask for async CPU-bound tasks via ProcessPoolExecutor."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
import logging

from asynctasq.tasks.core.base_task import BaseTask
from asynctasq.tasks.infrastructure.process_pool_manager import (
    ProcessPoolManager,
    get_warm_event_loop,
    increment_fallback_count,
)

logger = logging.getLogger(__name__)


class AsyncProcessTask[T](BaseTask[T]):
    """Async CPU-bound task via ProcessPoolExecutor with warm event loops.

    For async CPU-bound work (e.g., ML inference with async preprocessing).
    For I/O-bound work, use AsyncTask.
    """

    async def run(self) -> T:
        """Execute task via ProcessPoolExecutor with warm event loop."""
        # Get process pool (auto-initializes if needed)
        pool = ProcessPoolManager.get_async_pool()

        # Get current event loop
        loop = asyncio.get_running_loop()

        # Run execute() in process pool with asyncio.run() wrapper
        return await loop.run_in_executor(pool, self._run_async_in_process)

    def _run_async_in_process(self) -> T:
        """Run async execute() using warm event loop (falls back to asyncio.run())."""
        process_loop = get_warm_event_loop()

        if process_loop is not None:
            # Use warm event loop (fast path)
            future = asyncio.run_coroutine_threadsafe(self.execute(), process_loop)
            return future.result()
        else:
            # Fallback to asyncio.run() if warm loop not initialized
            current_count = increment_fallback_count()

            logger.warning(
                "Warm event loop not available, falling back to asyncio.run()",
                extra={
                    "task_class": self.__class__.__name__,
                    "fallback_count": current_count,
                    "performance_impact": "high",
                    "recommendation": "Call ProcessPoolManager.warm_up() during worker startup",
                },
            )
            return asyncio.run(self.execute())

    @abstractmethod
    async def execute(self) -> T:
        """Execute async CPU-bound logic (user implementation, runs in subprocess).

        Note:
            Arguments and return value must be serializable (msgpack-compatible).
        """
        ...
