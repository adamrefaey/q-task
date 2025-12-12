"""Type guards and type checking utilities for task types."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from asynctasq.tasks.core.base_task import BaseTask
    from asynctasq.tasks.types.function_task import FunctionTask


def is_function_task_instance(task: BaseTask) -> TypeGuard[FunctionTask]:
    """Check if task is a FunctionTask instance.

    Args:
        task: Task instance to check

    Returns:
        True if task is FunctionTask instance
    """
    from asynctasq.tasks.types.function_task import FunctionTask

    return isinstance(task, FunctionTask)


def is_function_task_class(task_class: type) -> bool:
    """Check if class is FunctionTask (not an instance check).

    Args:
        task_class: Class to check

    Returns:
        True if class is FunctionTask
    """
    from asynctasq.tasks.types.function_task import FunctionTask

    return task_class is FunctionTask
