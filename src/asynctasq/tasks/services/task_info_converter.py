"""TaskInfo conversion from raw task bytes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asynctasq.core.models import TaskInfo
from asynctasq.serializers.base_serializer import BaseSerializer


class TaskInfoConverter:
    """Converts raw bytes to TaskInfo models for monitoring/inspection."""

    def __init__(self, serializer: BaseSerializer) -> None:
        """Initialize with serializer for bytes → dict conversion."""
        self.serializer = serializer

    async def convert(
        self, raw_bytes: bytes, queue_name: str | None, status: str | None
    ) -> TaskInfo:
        """Convert raw bytes to TaskInfo.

        Returns:
            TaskInfo with extracted metadata (minimal TaskInfo on deserialization errors)
        """
        try:
            task_dict = await self.serializer.deserialize(raw_bytes)
        except Exception:
            # Return a minimal TaskInfo on deserialization error
            return TaskInfo(
                id="unknown",
                name="unknown",
                queue=queue_name or "unknown",
                status=status or "unknown",
                enqueued_at=datetime.now(UTC),
            )

        # Extract task info from the serialized format
        # Handle both flat format and nested format (class/params/metadata)
        if "metadata" in task_dict:
            # Nested format from serialize()
            metadata = task_dict.get("metadata", {})
            task_id = metadata.get("task_id", "unknown")

            # Extract class name from "module.ClassName" format
            class_path = task_dict.get("class", "unknown")
            task_name = class_path.rsplit(".", 1)[-1] if "." in class_path else class_path

            enqueued_at = self._parse_datetime(metadata.get("dispatched_at")) or datetime.now(UTC)
            queue = metadata.get("queue", queue_name)
        else:
            # Flat format (legacy or direct)
            task_id = task_dict.get("task_id", task_dict.get("id", "unknown"))
            task_name = task_dict.get("task_name", task_dict.get("name", "unknown"))
            enqueued_at = self._parse_datetime(task_dict.get("enqueued_at")) or datetime.now(UTC)
            queue = task_dict.get("queue", queue_name)

        # Parse optional datetime fields
        started_at = self._parse_datetime(task_dict.get("started_at"))
        completed_at = self._parse_datetime(task_dict.get("completed_at"))

        return TaskInfo(
            id=task_id,
            name=task_name,
            queue=queue,
            status=task_dict.get("status", status or "unknown"),
            enqueued_at=enqueued_at,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=task_dict.get("duration_ms"),
            worker_id=task_dict.get("worker_id"),
            attempt=task_dict.get("attempt", task_dict.get("metadata", {}).get("attempts", 1)),
            max_retries=task_dict.get(
                "max_retries", task_dict.get("metadata", {}).get("max_retries", 3)
            ),
            args=task_dict.get("args", task_dict.get("params")),
            kwargs=task_dict.get("kwargs"),
            result=task_dict.get("result"),
            exception=task_dict.get("exception"),
            traceback=task_dict.get("traceback"),
            priority=task_dict.get("priority", 0),
            timeout_seconds=task_dict.get(
                "timeout_seconds", task_dict.get("metadata", {}).get("timeout")
            ),
            tags=task_dict.get("tags"),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse datetime from various formats (None, str, int, float, datetime).

        Returns:
            Parsed datetime or None
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, UTC)
            except (ValueError, OSError):
                return None
        return None
