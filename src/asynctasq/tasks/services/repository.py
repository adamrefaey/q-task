"""Task repository for persistence and queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from asynctasq.core.models import TaskInfo

if TYPE_CHECKING:
    from asynctasq.drivers.base_driver import BaseDriver
    from asynctasq.tasks.services.serializer import TaskSerializer


class TaskRepository:
    """Task repository for queries and persistence (Repository pattern)."""

    def __init__(
        self,
        driver: BaseDriver,
        serializer: TaskSerializer,
        scan_limit: int = 10000,
    ) -> None:
        """Initialize with driver and serializer."""
        self.driver = driver
        self.scan_limit = scan_limit
        self.serializer = serializer

    async def get_running_tasks(self, limit: int = 50, offset: int = 0) -> list[tuple[bytes, str]]:
        """Get running tasks as raw data."""
        return await self.driver.get_running_tasks(limit=limit, offset=offset)

    async def get_running_task_infos(self, limit: int = 50, offset: int = 0) -> list[TaskInfo]:
        """Get running tasks as TaskInfo models."""
        raw_tasks = await self.get_running_tasks(limit=limit, offset=offset)
        task_infos = []
        for raw_bytes, queue_name in raw_tasks:
            task_info = await self.serializer.to_task_info(raw_bytes, queue_name, "running")
            task_infos.append(task_info)
        return task_infos

    async def get_tasks(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[bytes, str, str]], int]:
        """Get raw task data with pagination and filtering."""
        return await self.driver.get_tasks(status=status, queue=queue, limit=limit, offset=offset)

    async def get_task_infos(
        self,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TaskInfo], int]:
        """Get tasks as TaskInfo models with pagination and filtering."""
        raw_tasks, total = await self.get_tasks(
            status=status, queue=queue, limit=limit, offset=offset
        )
        task_infos = []
        for raw_bytes, queue_name, task_status in raw_tasks:
            task_info = await self.serializer.to_task_info(raw_bytes, queue_name, task_status)
            task_infos.append(task_info)
        return task_infos, total

    async def _find_task_with_metadata(
        self, task_id: str
    ) -> tuple[bytes, str | None, str | None] | None:
        """Find task with metadata (efficient lookup or scan fallback)."""
        # Try efficient lookup first
        raw_bytes = await self.driver.get_task_by_id(task_id)
        if raw_bytes is not None:
            return (raw_bytes, None, None)

        # Fallback to scanning
        raw_tasks, _ = await self.driver.get_tasks(
            status=None, queue=None, limit=self.scan_limit, offset=0
        )
        for raw_bytes, queue_name, status in raw_tasks:
            try:
                task_dict = await self.serializer.serializer.deserialize(raw_bytes)
                if self._extract_task_id(task_dict) == task_id:
                    return (raw_bytes, queue_name, status)
            except Exception:
                continue
        return None

    def _extract_task_id(self, task_dict: dict) -> str | None:
        """Extract task ID from serialized dict (handles nested and flat formats)."""
        if "metadata" in task_dict:
            return task_dict.get("metadata", {}).get("task_id")
        return task_dict.get("task_id", task_dict.get("id"))

    async def get_task_by_id(self, task_id: str) -> tuple[bytes, str | None, str | None] | None:
        """Get raw task by ID (efficient lookup or scan fallback)."""
        return await self._find_task_with_metadata(task_id)

    async def get_task_info_by_id(self, task_id: str) -> TaskInfo | None:
        """Get task as TaskInfo model by ID."""
        result = await self.get_task_by_id(task_id)
        if result is None:
            return None

        raw_bytes, queue_name, status = result
        return await self.serializer.to_task_info(raw_bytes, queue_name, status)

    async def delete_task(self, task_id: str) -> bool:
        """Delete task by ID (efficient delete or scan fallback)."""
        # Try driver's direct delete first (efficient for Postgres/MySQL)
        if await self.driver.delete_task(task_id):
            return True

        # Fall back to find + delete_raw_task (for Redis)
        result = await self._find_task_with_metadata(task_id)
        if result is None:
            return False

        raw_bytes, queue_name, _ = result
        # queue_name may be None from efficient lookup, but delete_raw_task handles it
        if queue_name is None:
            # If we don't have queue_name, we can't use delete_raw_task
            return False
        return await self.driver.delete_raw_task(queue_name, raw_bytes)
