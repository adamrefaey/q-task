"""
Monitoring service that provides typed access to queue statistics.

This service wraps a driver and converts raw data from the driver
into typed models (QueueStats, WorkerInfo, TaskInfo) for monitoring purposes.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from asynctasq.core.models import QueueStats, TaskInfo, WorkerInfo
from asynctasq.tasks.services.executor import TaskExecutor
from asynctasq.tasks.services.repository import TaskRepository
from asynctasq.tasks.services.serializer import TaskSerializer

if TYPE_CHECKING:
    from asynctasq.drivers.base_driver import BaseDriver
    from asynctasq.serializers.base_serializer import BaseSerializer


@dataclass
class MonitoringService:
    """
    Service layer for monitoring queue operations.

    Converts raw driver data into typed models for monitoring UIs,
    dashboards, and other consumers that need structured data.

    Task-specific operations are delegated to TaskService.
    """

    driver: "BaseDriver"
    serializer: "BaseSerializer | None" = None
    _task_serializer: TaskSerializer = field(init=False)
    _task_executor: TaskExecutor = field(init=False)
    _task_repository: TaskRepository = field(init=False)

    def __post_init__(self) -> None:
        self._task_serializer = TaskSerializer(self.serializer)
        self._task_repository = TaskRepository(self.driver, self._task_serializer)
        self._task_executor = TaskExecutor(
            self.driver, self._task_serializer, self._task_repository
        )

    async def get_queue_stats(self, queue: str) -> QueueStats:
        """
        Get statistics for a specific queue.

        Args:
            queue: Queue name

        Returns:
            QueueStats model with queue statistics
        """
        raw = await self.driver.get_queue_stats(queue)
        return QueueStats(
            name=raw.get("name", queue),
            depth=raw.get("depth", 0),
            processing=raw.get("processing", 0),
            completed_total=raw.get("completed_total", 0),
            failed_total=raw.get("failed_total", 0),
            avg_duration_ms=raw.get("avg_duration_ms"),
            throughput_per_minute=raw.get("throughput_per_minute"),
        )

    async def get_all_queue_stats(self) -> list[QueueStats]:
        """
        Get statistics for all queues.

        Returns:
            List of QueueStats for all known queues
        """
        queue_names = await self.driver.get_all_queue_names()
        stats = []
        for name in queue_names:
            queue_stats = await self.get_queue_stats(name)
            stats.append(queue_stats)
        return stats

    async def get_global_stats(self) -> dict[str, int]:
        """
        Get global task statistics across all queues.

        Returns:
            Dict with keys: pending, running, completed, failed, total
        """
        return await self.driver.get_global_stats()

    async def get_worker_stats(self) -> list[WorkerInfo]:
        """
        Get statistics for all active workers.

        Returns:
            List of WorkerInfo models
        """
        raw_workers = await self.driver.get_worker_stats()
        workers = []
        for raw in raw_workers:
            last_heartbeat = None
            if raw.get("last_heartbeat"):
                hb = raw["last_heartbeat"]
                if isinstance(hb, datetime):
                    last_heartbeat = hb
                elif isinstance(hb, str):
                    try:
                        last_heartbeat = datetime.fromisoformat(hb)
                    except ValueError:
                        pass
                elif isinstance(hb, (int, float)):
                    last_heartbeat = datetime.fromtimestamp(hb, UTC)

            workers.append(
                WorkerInfo(
                    worker_id=raw.get("worker_id", "unknown"),
                    status=raw.get("status", "unknown"),
                    current_task_id=raw.get("current_task_id"),
                    tasks_processed=raw.get("tasks_processed", 0),
                    uptime_seconds=raw.get("uptime_seconds", 0),
                    last_heartbeat=last_heartbeat,
                    load_percentage=raw.get("load_percentage", 0.0),
                )
            )
        return workers

    async def get_running_tasks(self, limit: int = 50, offset: int = 0) -> list[tuple[bytes, str]]:
        """
        Get currently running tasks.

        Args:
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            List of (raw_bytes, queue_name) tuples
        """
        return await self._task_repository.get_running_tasks(limit=limit, offset=offset)

    async def get_running_task_infos(self, limit: int = 50, offset: int = 0) -> list[TaskInfo]:
        """
        Get currently running tasks as TaskInfo models.

        Args:
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            List of TaskInfo models
        """
        return await self._task_repository.get_running_task_infos(limit=limit, offset=offset)

    async def get_tasks(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[bytes, str, str]], int]:
        """
        Get raw task data with pagination.

        Args:
            status: Filter by status (pending, running)
            queue: Filter by queue name
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            Tuple of (list of (raw_bytes, queue_name, status), total_count)
        """
        return await self._task_repository.get_tasks(
            status=status, queue=queue, limit=limit, offset=offset
        )

    async def get_task_infos(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TaskInfo], int]:
        """
        Get tasks as TaskInfo models with pagination.

        Args:
            status: Filter by status (pending, running)
            queue: Filter by queue name
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            Tuple of (list of TaskInfo, total_count)
        """
        return await self._task_repository.get_task_infos(
            status=status, queue=queue, limit=limit, offset=offset
        )

    async def get_task_by_id(self, task_id: str) -> tuple[bytes, str | None, str | None] | None:
        """
        Get raw task data by ID.

        Args:
            task_id: Task UUID

        Returns:
            Tuple of (raw_bytes, queue_name_or_none, status_or_none) or None if not found.
            queue_name and status are None when using efficient driver lookup.
        """
        return await self._task_repository.get_task_by_id(task_id)

    async def get_task_info_by_id(self, task_id: str) -> TaskInfo | None:
        """
        Get task as TaskInfo model by ID.

        Args:
            task_id: Task UUID

        Returns:
            TaskInfo or None if not found
        """
        return await self._task_repository.get_task_info_by_id(task_id)

    async def retry_task(self, task_id: str) -> bool:
        """
        Retry a failed task.

        Args:
            task_id: Task UUID to retry

        Returns:
            True if successfully re-enqueued
        """
        return await self._task_executor.retry_task(task_id)

    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: Task UUID to delete

        Returns:
            True if deleted
        """
        return await self._task_repository.delete_task(task_id)

    async def get_all_queue_names(self) -> list[str]:
        """
        Get all queue names.

        Returns:
            List of queue names
        """
        return await self.driver.get_all_queue_names()
