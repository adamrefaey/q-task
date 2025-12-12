"""Tests for task lifecycle hooks (before_execute, after_execute)."""

from __future__ import annotations

import asyncio
import time

from asynctasq.tasks import AsyncTask, SyncTask


class HookedAsyncTask(AsyncTask[str]):
    """Task with lifecycle hooks for testing."""

    def __init__(self, value: str, should_fail: bool = False) -> None:
        super().__init__()
        self.value = value
        self.should_fail = should_fail
        self.before_called = False
        self.after_called = False
        self.start_time: float | None = None
        self.end_time: float | None = None

    async def execute(self) -> str:
        """Execute task logic."""
        if self.should_fail:
            raise ValueError("Task execution failed")
        await asyncio.sleep(0.01)  # Simulate work
        return f"processed_{self.value}"

    async def before_execute(self) -> None:
        """Hook called before execution."""
        self.before_called = True
        self.start_time = time.time()

    async def after_execute(self, result: str) -> None:
        """Hook called after execution."""
        self.after_called = True
        self.end_time = time.time()


class HookedSyncTask(SyncTask[int]):
    """Sync task with lifecycle hooks for testing."""

    def __init__(self, value: int) -> None:
        super().__init__()
        self.value = value
        self.before_called = False
        self.after_called = False

    def execute(self) -> int:
        """Execute task logic."""
        return self.value * 2

    async def before_execute(self) -> None:
        """Hook called before execution."""
        self.before_called = True

    async def after_execute(self, result: int) -> None:
        """Hook called after execution."""
        self.after_called = True


class BeforeExecuteFailureTask(AsyncTask[str]):
    """Task where before_execute raises exception."""

    async def execute(self) -> str:
        return "success"

    async def before_execute(self) -> None:
        raise RuntimeError("before_execute failed")


class AfterExecuteFailureTask(AsyncTask[str]):
    """Task where after_execute raises exception."""

    async def execute(self) -> str:
        return "success"

    async def after_execute(self, result: str) -> None:
        raise RuntimeError("after_execute failed")
