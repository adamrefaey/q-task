"""Task execution and lifecycle management.

Framework-level error handling: timeout, retry logic, user hooks (should_retry, failed).
See docs/error-handling-architecture.md for complete documentation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asynctasq.drivers.base_driver import BaseDriver
    from asynctasq.tasks.core.base_task import BaseTask
    from asynctasq.tasks.services.repository import TaskRepository
    from asynctasq.tasks.services.serializer import TaskSerializer

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Handles task execution, retry logic, and lifecycle hooks."""

    def __init__(
        self,
        driver: BaseDriver | None = None,
        serializer: TaskSerializer | None = None,
        repository: TaskRepository | None = None,
    ) -> None:
        """Initialize with optional dependencies."""
        self.driver = driver
        self.serializer = serializer
        self.repository = repository

    async def execute(self, task: BaseTask, timeout: float | None = None) -> None:
        """Execute task with timeout (framework entry point).

        Wraps task.run() with timeout. Caller handles exceptions.

        Args:
            task: Task instance to execute
            timeout: Optional timeout override (uses task.config.timeout if None)

        Raises:
            Exception: Any exception from task.run()
        """
        effective_timeout = timeout or task.config.timeout

        if effective_timeout:
            await asyncio.wait_for(task.run(), timeout=effective_timeout)
        else:
            await task.run()

    def should_retry(self, task: BaseTask, exception: Exception) -> bool:
        """Determine if task should retry after exception.

        Combines framework policy (attempts < max_retries) with user policy (task.should_retry()).

        Args:
            task: Task that failed
            exception: Exception that occurred

        Returns:
            True to retry, False if permanently failed
        """
        return task._attempts < task.config.max_retries and task.should_retry(exception)

    def prepare_retry(self, task: BaseTask) -> BaseTask:
        """Increment attempts for retry.

        Args:
            task: Task to prepare

        Returns:
            Task with incremented _attempts (caller must serialize and re-queue)
        """
        task._attempts += 1
        return task

    async def handle_failed(self, task: BaseTask, exception: Exception) -> None:
        """Call task.failed() hook when retries exhausted (best-effort).

        Args:
            task: Task that permanently failed
            exception: Exception that caused failure
        """
        try:
            await task.failed(exception)
        except Exception as e:
            from asynctasq.tasks.utils.logger import log_task_error

            log_task_error(
                task, "Error in task.failed() handler", error=str(e), original_error=str(exception)
            )

    async def retry_task(self, task_id: str) -> bool:
        """Retry failed task by ID.

        Tries driver.retry_task() first, falls back to repository lookup.

        Args:
            task_id: Task ID to retry

        Returns:
            True if retry succeeded, False otherwise

        Raises:
            ValueError: If driver or repository not configured
        """
        if self.driver is None:
            raise ValueError("Driver required for retry_task operation")

        # Try driver's direct retry first (efficient for Postgres/MySQL)
        if await self.driver.retry_task(task_id):
            return True

        # Fall back to repository lookup + retry_raw_task (for Redis)
        if self.repository is None:
            raise ValueError(
                "TaskRepository required for retry_task fallback when driver "
                "doesn't support efficient ID-based retry"
            )

        result = await self.repository._find_task_with_metadata(task_id)
        if result is None:
            return False

        raw_bytes, queue_name, _ = result
        # queue_name may be None from efficient lookup, but retry_raw_task handles it
        if queue_name is None:
            # If we don't have queue_name, we can't use retry_raw_task
            return False
        return await self.driver.retry_raw_task(queue_name, raw_bytes)
