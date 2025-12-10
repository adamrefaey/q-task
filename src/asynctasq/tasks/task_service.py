"""
Task service that handles task serialization, deserialization, and query operations.

This service centralizes all task-related operations:
- Serialization: BaseTask instance -> bytes (for queueing)
- Deserialization: bytes -> BaseTask instance (for execution)
- Task execution: execute with timeout, retry logic
- Task info parsing: bytes -> TaskInfo model (for monitoring)
- Task queries: get, list, retry, delete operations
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from asynctasq.core.models import TaskInfo
from asynctasq.serializers.base_serializer import BaseSerializer
from asynctasq.serializers.msgpack_serializer import MsgpackSerializer

if TYPE_CHECKING:
    from asynctasq.drivers.base_driver import BaseDriver

    from .base_task import BaseTask

logger = logging.getLogger(__name__)


@dataclass
class TaskService:
    """Service for task serialization, deserialization, and query operations.

    Centralizes all task-handling logic with best practices for async operations:

    ## Core Operations

    - **Serialization**: BaseTask instance → bytes (for queueing)
    - **Deserialization**: bytes → BaseTask instance (for execution)
    - **Execution**: Run task.handle() with timeout support
    - **Monitoring**: Parse bytes → TaskInfo models
    - **Persistence**: Query/mutate tasks in driver

    ## Best Practices Implemented

    - **Type safety**: Full type hints for all operations
    - **Timeout handling**: Configurable task execution timeouts
    - **Error context**: Proper exception context preservation
    - **Datetime handling**: Robust parsing from multiple formats
    - **ORM integration**: Automatic serialization of SQLAlchemy/Django models

    ## Retry Logic

    Determines if a task should retry based on:
    - Attempt count < max_retries
    - Custom task.should_retry(exception) logic
    - Configurable exponential backoff

    ## Attributes

        serializer: BaseSerializer instance (defaults to MsgpackSerializer)
        driver: Optional BaseDriver for query operations
    """

    serializer: BaseSerializer | None = None
    driver: "BaseDriver | None" = None

    def __post_init__(self) -> None:
        if self.serializer is None:
            self.serializer = MsgpackSerializer()

    # =========================================================================
    # Serialization (Task -> bytes)
    # =========================================================================

    def serialize_task(self, task: "BaseTask") -> bytes:
        """
        Serialize a task instance to bytes for queue storage.

        Serialization includes:
        - Task class path (for reconstruction)
        - Task parameters (non-internal attributes)
        - Task metadata (_task_id, _attempts, etc.)
        - Task configuration (queue, max_retries, etc.)

        Args:
            task: BaseTask instance to serialize

        Returns:
            bytes: Serialized task data
        """
        assert self.serializer is not None

        # Filter out private attributes and callable objects (like functions)
        params = {
            k: v for k, v in task.__dict__.items() if not k.startswith("_") and not callable(v)
        }

        # Build metadata
        metadata: dict[str, Any] = {
            "task_id": task._task_id,
            "attempts": task._attempts,
            "dispatched_at": task._dispatched_at.isoformat() if task._dispatched_at else None,
            "max_retries": task.max_retries,
            "retry_delay": task.retry_delay,
            "timeout": task.timeout,
            "queue": task.queue,
        }

        # For FunctionTask, store function reference instead of function object
        if self._is_function_task(task):
            func = task.func  # type: ignore[attr-defined]
            metadata["func_name"] = func.__name__

            # Handle __main__ module specially - store file path instead
            if func.__module__ == "__main__":
                try:
                    file_path = inspect.getfile(func)
                    metadata["func_module"] = "__main__"
                    metadata["func_file"] = file_path
                except (TypeError, OSError):
                    # Fallback if we can't get the file path
                    metadata["func_module"] = func.__module__
            else:
                metadata["func_module"] = func.__module__

        task_data = {
            "class": f"{task.__class__.__module__}.{task.__class__.__name__}",
            "params": params,
            "metadata": metadata,
        }

        return self.serializer.serialize(task_data)

    # =========================================================================
    # Deserialization (bytes -> BaseTask instance)
    # =========================================================================

    async def deserialize_task(self, task_data: bytes) -> "BaseTask":
        """
        Deserialize task from bytes and reconstruct the task instance.

        Reconstruction process:
        1. Deserialize bytes to dictionary using serializer
        2. Import task class from 'class' field (module.ClassName)
        3. Create task instance without calling __init__
        4. Restore task parameters from 'params' dict
        5. Restore internal metadata (_task_id, _attempts, etc.)

        Args:
            task_data: Serialized task bytes

        Returns:
            Task: Fully reconstructed task instance

        Raises:
            ImportError: If task class cannot be imported
            AttributeError: If task class not found in module
        """
        assert self.serializer is not None

        data = await self.serializer.deserialize(task_data)

        # Import task class
        module_name, class_name = data["class"].rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        task_class = getattr(module, class_name)

        # Reconstruct task without calling __init__
        task = task_class.__new__(task_class)
        task.__dict__.update(data["params"])

        # Restore metadata with proper type conversions
        metadata = data["metadata"]
        task._task_id = metadata.get("task_id")
        task._attempts = metadata.get("attempts", 0)

        # Restore dispatched_at as datetime if present
        dispatched_at_str = metadata.get("dispatched_at")
        if dispatched_at_str:
            try:
                task._dispatched_at = datetime.fromisoformat(dispatched_at_str)
            except (ValueError, TypeError):
                task._dispatched_at = None
        else:
            task._dispatched_at = None

        # Restore task configuration from metadata
        if "max_retries" in metadata:
            task.max_retries = metadata["max_retries"]
        if "retry_delay" in metadata:
            task.retry_delay = metadata["retry_delay"]
        if "timeout" in metadata:
            task.timeout = metadata["timeout"]
        if "queue" in metadata:
            task.queue = metadata["queue"]

        # For FunctionTask, reconstruct function reference from metadata
        if class_name == "FunctionTask" and "func_module" in metadata and "func_name" in metadata:
            self._reconstruct_function_task(task, metadata)

        return task

    def _reconstruct_function_task(self, task: "BaseTask", metadata: dict[str, Any]) -> None:
        """
        Reconstruct the function reference for a FunctionTask.

        Handles both regular modules and __main__ module (loading from file path).
        """
        func_module_name = metadata["func_module"]
        func_name = metadata["func_name"]

        # Handle __main__ module - load from file path
        if func_module_name == "__main__" and "func_file" in metadata:
            func_file = Path(metadata["func_file"])
            # Use a unique module name based on file path to avoid conflicts
            # and prevent re-execution of __main__ blocks
            unique_module_name = f"__main___{func_file.stem}_{hash(func_file)}"
            spec = importlib.util.spec_from_file_location(unique_module_name, func_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load module from file: {func_file}")
            func_module = importlib.util.module_from_spec(spec)
            # Set __name__ to the unique name to prevent __main__ block execution
            func_module.__name__ = unique_module_name
            try:
                spec.loader.exec_module(func_module)
            except RuntimeError as e:
                # Catch RuntimeError from asyncio.run() or similar calls at module level
                if "asyncio.run() cannot be called from a running event loop" in str(e):
                    logger.debug(
                        f"Suppressed asyncio.run() error when loading module {func_file}: {e}"
                    )
                    if not hasattr(func_module, func_name):
                        raise AttributeError(
                            f"Function '{func_name}' not found in module {func_file} "
                            f"after suppressing asyncio.run() error"
                        ) from None
                else:
                    raise
        else:
            func_module = __import__(func_module_name, fromlist=[func_name])

        task.func = getattr(func_module, func_name)  # type: ignore[attr-defined]

    # =========================================================================
    # Task Execution
    # =========================================================================

    async def execute_task(self, task: "BaseTask") -> None:
        """
        Execute a task's handle() method with optional timeout.

        Args:
            task: BaseTask instance to execute

        Raises:
            TimeoutError: If task exceeds configured timeout
            Exception: Any exception raised by task.handle()
        """
        if task.timeout:
            await asyncio.wait_for(task.handle(), timeout=task.timeout)
        else:
            await task.handle()

    def should_retry(self, task: "BaseTask", exception: Exception) -> bool:
        """
        Determine if a task should be retried after failure.

        Checks:
        1. task._attempts < task.max_retries
        2. task.should_retry(exception) returns True

        Args:
            task: Failed task instance
            exception: Exception that caused the failure

        Returns:
            True if task should be retried
        """
        return task._attempts < task.max_retries and task.should_retry(exception)

    def prepare_for_retry(self, task: "BaseTask") -> bytes:
        """
        Prepare a task for retry by incrementing attempts and serializing.

        This method:
        1. Increments task._attempts
        2. Serializes the task for re-enqueueing

        Args:
            task: Task to prepare for retry

        Returns:
            Serialized task bytes ready for enqueueing
        """
        task._attempts += 1
        return self.serialize_task(task)

    async def handle_task_failed(self, task: "BaseTask", exception: Exception) -> None:
        """
        Call the task's failed() hook for permanent failures.

        This should be called when a task has exhausted all retries.

        Args:
            task: Failed task instance
            exception: Final exception that caused the failure
        """
        try:
            await task.failed(exception)
        except Exception as e:
            logger.exception(f"Error in task.failed() handler: {e}")

    # =========================================================================
    # Task Info Parsing (bytes -> TaskInfo model for monitoring)
    # =========================================================================

    async def deserialize_to_task_info(
        self, raw_bytes: bytes, queue_name: str, status: str
    ) -> TaskInfo:
        """
        Deserialize raw bytes to TaskInfo model for monitoring purposes.

        This is a lighter-weight operation than full task reconstruction,
        extracting only the data needed for monitoring UIs.

        Args:
            raw_bytes: Raw serialized bytes
            queue_name: Queue the task is in
            status: Current task status

        Returns:
            TaskInfo model
        """
        assert self.serializer is not None

        try:
            task_dict = await self.serializer.deserialize(raw_bytes)
        except Exception:
            # Return a minimal TaskInfo on deserialization error
            return TaskInfo(
                id="unknown",
                name="unknown",
                queue=queue_name,
                status=status,
                enqueued_at=datetime.now(UTC),
            )

        # Extract task info from the serialized format
        # Handle both flat format and nested format (class/params/metadata)
        if "metadata" in task_dict:
            # Nested format from serialize_task()
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
            status=task_dict.get("status", status),
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

    # =========================================================================
    # Task Query Operations (requires driver)
    # =========================================================================

    def _require_driver(self) -> "BaseDriver":
        """Ensure driver is configured for query operations."""
        if self.driver is None:
            raise ValueError("Driver required for task query operations")
        return self.driver

    async def get_running_tasks(self, limit: int = 50, offset: int = 0) -> list[tuple[bytes, str]]:
        """
        Get currently running tasks as raw data.

        Args:
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            List of (raw_bytes, queue_name) tuples
        """
        driver = self._require_driver()
        return await driver.get_running_tasks(limit=limit, offset=offset)

    async def get_running_task_infos(self, limit: int = 50, offset: int = 0) -> list[TaskInfo]:
        """
        Get currently running tasks as TaskInfo models.

        Args:
            limit: Maximum tasks to return
            offset: Pagination offset

        Returns:
            List of TaskInfo models
        """
        raw_tasks = await self.get_running_tasks(limit=limit, offset=offset)
        task_infos = []
        for raw_bytes, queue_name in raw_tasks:
            task_info = await self.deserialize_to_task_info(raw_bytes, queue_name, "running")
            task_infos.append(task_info)
        return task_infos

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
        driver = self._require_driver()
        return await driver.get_tasks(status=status, queue=queue, limit=limit, offset=offset)

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
        raw_tasks, total = await self.get_tasks(
            status=status, queue=queue, limit=limit, offset=offset
        )
        task_infos = []
        for raw_bytes, queue_name, task_status in raw_tasks:
            task_info = await self.deserialize_to_task_info(raw_bytes, queue_name, task_status)
            task_infos.append(task_info)
        return task_infos, total

    async def get_task_by_id(self, task_id: str) -> tuple[bytes, str, str] | None:
        """
        Get raw task data by ID.

        First tries driver.get_task_by_id() for drivers that support efficient
        primary key lookups (PostgreSQL, MySQL). If that returns None,
        falls back to scanning all tasks.

        Args:
            task_id: Task UUID

        Returns:
            Tuple of (raw_bytes, queue_name, status) or None if not found
        """
        driver = self._require_driver()

        # Try driver's direct lookup first (efficient for Postgres/MySQL)
        raw_bytes = await driver.get_task_by_id(task_id)
        if raw_bytes is not None:
            return (raw_bytes, "unknown", "unknown")

        # Fall back to scanning all tasks
        raw_tasks, _ = await driver.get_tasks(status=None, queue=None, limit=10000, offset=0)
        for raw_bytes, queue_name, status in raw_tasks:
            try:
                assert self.serializer is not None
                task_dict = await self.serializer.deserialize(raw_bytes)
                # Handle nested format
                if "metadata" in task_dict:
                    if task_dict.get("metadata", {}).get("task_id") == task_id:
                        return (raw_bytes, queue_name, status)
                elif task_dict.get("task_id") == task_id:
                    return (raw_bytes, queue_name, status)
            except Exception:
                continue

        return None

    async def get_task_info_by_id(self, task_id: str) -> TaskInfo | None:
        """
        Get task as TaskInfo model by ID.

        Args:
            task_id: Task UUID

        Returns:
            TaskInfo or None if not found
        """
        result = await self.get_task_by_id(task_id)
        if result is None:
            return None

        raw_bytes, queue_name, status = result
        return await self.deserialize_to_task_info(raw_bytes, queue_name, status)

    async def retry_task(self, task_id: str) -> bool:
        """
        Retry a failed task.

        First tries driver.retry_task() for drivers with efficient ID-based
        retry (PostgreSQL, MySQL). If that returns False, falls back to
        scanning all tasks, finding by ID via deserialization, and using
        retry_raw_task().

        Args:
            task_id: Task UUID to retry

        Returns:
            True if successfully re-enqueued
        """
        driver = self._require_driver()

        # Try driver's direct retry first (efficient for Postgres/MySQL)
        if await driver.retry_task(task_id):
            return True

        # Fall back to scan + deserialize + retry_raw_task (for Redis)
        result = await self.get_task_by_id(task_id)
        if result is None:
            return False

        raw_bytes, queue_name, _ = result
        return await driver.retry_raw_task(queue_name, raw_bytes)

    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task by ID.

        First tries driver.delete_task() for drivers with efficient ID-based
        deletion (PostgreSQL, MySQL). If that returns False, falls back to
        scanning all tasks, finding by ID via deserialization, and using
        delete_raw_task().

        Args:
            task_id: Task UUID to delete

        Returns:
            True if deleted
        """
        driver = self._require_driver()

        # Try driver's direct delete first (efficient for Postgres/MySQL)
        if await driver.delete_task(task_id):
            return True

        # Fall back to scan + deserialize + delete_raw_task (for Redis)
        result = await self.get_task_by_id(task_id)
        if result is None:
            return False

        raw_bytes, queue_name, _ = result
        return await driver.delete_raw_task(queue_name, raw_bytes)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _parse_datetime(self, value: Any) -> datetime | None:
        """Parse a datetime from various formats (string, timestamp, datetime)."""
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

    def _is_function_task(self, task: "BaseTask") -> bool:
        """Check if task is a FunctionTask without importing it."""
        return task.__class__.__name__ == "FunctionTask"
