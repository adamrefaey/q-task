"""Shared test fixtures and utilities for task testing.

This module provides reusable utilities to eliminate code duplication
across test files, particularly for common task patterns.
"""

import asyncio

from asynctasq.tasks import AsyncProcessTask, SyncProcessTask


def factorial(n: int) -> int:
    """Pure factorial function (no task logic).

    Args:
        n: The number to compute factorial of

    Returns:
        Factorial of n
    """
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result


# Module-level task classes (needed for pickling in process pool)
class SharedSyncFactorialTask(SyncProcessTask[int]):
    """Shared test task that computes factorial in separate process."""

    n: int

    def execute(self) -> int:
        """Compute factorial of self.n."""
        return factorial(self.n)


class SharedAsyncFactorialTask(AsyncProcessTask[int]):
    """Shared test task that computes factorial asynchronously in separate process."""

    n: int

    async def execute(self) -> int:
        """Compute factorial of self.n asynchronously."""
        result = 1
        for i in range(1, self.n + 1):
            result *= i
            # Yield to event loop periodically
            if i % 1000 == 0:
                await asyncio.sleep(0)
        return result
