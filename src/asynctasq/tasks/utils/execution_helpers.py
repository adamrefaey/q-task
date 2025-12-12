"""Execution helpers for task types that need thread or process pool execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


async def execute_in_thread[T](sync_callable: Callable[[], T]) -> T:
    """Execute sync callable in ThreadPoolExecutor.

    Args:
        sync_callable: Synchronous function to execute

    Returns:
        Result from sync_callable
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, sync_callable)


async def execute_in_process_sync[T](sync_callable: Callable[[], T]) -> T:
    """Execute sync callable in ProcessPoolExecutor for CPU-bound work.

    Args:
        sync_callable: Synchronous function to execute

    Returns:
        Result from sync_callable
    """
    from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager

    pool = ProcessPoolManager.get_sync_pool()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(pool, sync_callable)
