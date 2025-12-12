"""Task serialization and deserialization (bytes ↔ BaseTask)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from asynctasq.serializers.base_serializer import BaseSerializer
from asynctasq.serializers.msgpack_serializer import MsgpackSerializer
from asynctasq.tasks.core.task_config import TaskConfig
from asynctasq.tasks.services.function_resolver import FunctionResolver
from asynctasq.tasks.services.task_info_converter import TaskInfoConverter
from asynctasq.tasks.utils.type_guards import is_function_task_class, is_function_task_instance

if TYPE_CHECKING:
    from asynctasq.core.models import TaskInfo
    from asynctasq.tasks.core.base_task import BaseTask


class TaskSerializer:
    """Task serializer (BaseTask ↔ bytes).

    Delegates TaskInfo conversion to TaskInfoConverter and function resolution to FunctionResolver.
    """

    def __init__(self, serializer: BaseSerializer | None = None) -> None:
        """Initialize with optional custom serializer (defaults to MsgpackSerializer)."""
        self.serializer = serializer or MsgpackSerializer()
        self._task_info_converter = TaskInfoConverter(self.serializer)
        self._function_resolver = FunctionResolver()

    def serialize(self, task: BaseTask) -> bytes:
        """Serialize task to bytes.

        Returns:
            Serialized task data
        """
        # Filter out private/internal attributes (those starting with _)
        # Also filter callables and config since they're handled separately
        params = {
            key: value
            for key, value in task.__dict__.items()
            if not key.startswith("_") and not callable(value) and key != "config"
        }

        # For FunctionTask, store func reference in params for now
        # They'll be moved to metadata below
        func_module = None
        func_name = None
        func_file = None
        if is_function_task_instance(task):
            func = task.func  # type: ignore[attr-defined]
            func_module = func.__module__
            func_name = func.__name__
            # Store func_file if it's __main__ module
            if func_module == "__main__":
                func_file = func.__code__.co_filename
            params["args"] = task.args  # type: ignore[attr-defined]
            params["kwargs"] = task.kwargs  # type: ignore[attr-defined]
            # Remove func and use_process from params since we can't/don't need to serialize them
            params.pop("func", None)
            params.pop("_use_process", None)

        # Build metadata
        metadata = {
            "task_id": task._task_id,
            "attempts": task._attempts,
            "dispatched_at": task._dispatched_at.isoformat() if task._dispatched_at else None,
            "queue": task.config.queue,
            "max_retries": task.config.max_retries,
            "retry_delay": task.config.retry_delay,
            "timeout": task.config.timeout,
        }

        # Add FunctionTask-specific metadata
        if is_function_task_instance(task):
            metadata["func_module"] = func_module
            metadata["func_name"] = func_name
            if func_file:
                metadata["func_file"] = func_file

        # Build serialization dict
        task_dict = {
            "class": f"{task.__class__.__module__}.{task.__class__.__name__}",
            "params": params,
            "metadata": metadata,
        }

        # Serialize to bytes
        return self.serializer.serialize(task_dict)

    async def deserialize(self, task_data: bytes) -> BaseTask:
        """Deserialize bytes to task instance.

        Returns:
            Task ready for execution

        Raises:
            ValueError: If FunctionTask metadata missing
            ImportError: If task class/function cannot be imported
        """
        # Deserialize bytes to dict
        task_dict = await self.serializer.deserialize(task_data)

        # Extract components
        class_path = task_dict["class"]
        params = task_dict["params"]
        metadata = task_dict["metadata"]

        # Import and instantiate task class
        module_name, class_name = class_path.rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        task_class = getattr(module, class_name)

        # Special handling for FunctionTask: need to restore func first, then create instance
        if is_function_task_class(task_class):
            # For FunctionTask, we need func before instantiating
            # Get func from metadata first
            func_module_name = metadata.get("func_module")
            func_name = metadata.get("func_name")

            if not func_module_name or not func_name:
                raise ValueError("FunctionTask missing func_module or func_name in metadata")

            # Restore func reference using FunctionResolver
            func = self._function_resolver.get_function_reference(
                func_module_name, func_name, metadata.get("func_file")
            )

            # Create FunctionTask with func and params
            task = task_class(func, *params.get("args", ()), **params.get("kwargs", {}))
        else:
            # Create task instance with params
            task = task_class(**params)

        # Restore metadata
        task._task_id = metadata["task_id"]
        task._attempts = metadata["attempts"]
        dispatched_at_str = metadata.get("dispatched_at")
        if dispatched_at_str:
            try:
                task._dispatched_at = datetime.fromisoformat(dispatched_at_str)
            except (ValueError, TypeError):
                # Invalid datetime format or wrong type
                task._dispatched_at = None

        # Restore config (use TaskConfig factory to handle driver resolution)
        task.config = TaskConfig(
            queue=metadata["queue"],
            max_retries=metadata["max_retries"],
            retry_delay=metadata["retry_delay"],
            timeout=metadata["timeout"],
        )

        return task

    async def to_task_info(
        self, raw_bytes: bytes, queue_name: str | None, status: str | None
    ) -> TaskInfo:
        """Convert raw bytes to TaskInfo (delegates to TaskInfoConverter).

        Returns:
            TaskInfo model with extracted metadata
        """
        return await self._task_info_converter.convert(raw_bytes, queue_name, status)
