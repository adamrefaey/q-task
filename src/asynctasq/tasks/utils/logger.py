"""Structured logging helpers for task context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asynctasq.tasks.core.base_task import BaseTask


def get_task_context(task: BaseTask) -> dict[str, Any]:
    """Extract logging context from task (task_id, class, queue, attempts, max_retries)."""
    return {
        "task_id": task._task_id,
        "task_class": task.__class__.__name__,
        "queue": task.config.queue,
        "attempts": task._attempts,
        "max_retries": task.config.max_retries,
    }


def log_task_info(task: BaseTask, message: str, **extra: Any) -> None:
    """Log info with task context."""
    logger = logging.getLogger(task.__class__.__module__)
    context = get_task_context(task)
    context.update(extra)
    logger.info(message, extra=context)


def log_task_debug(task: BaseTask, message: str, **extra: Any) -> None:
    """Log debug with task context."""
    logger = logging.getLogger(task.__class__.__module__)
    context = get_task_context(task)
    context.update(extra)
    logger.debug(message, extra=context)


def log_task_warning(task: BaseTask, message: str, **extra: Any) -> None:
    """Log warning with task context."""
    logger = logging.getLogger(task.__class__.__module__)
    context = get_task_context(task)
    context.update(extra)
    logger.warning(message, extra=context)


def log_task_error(task: BaseTask, message: str, exc_info: bool = True, **extra: Any) -> None:
    """Log error with task context."""
    logger = logging.getLogger(task.__class__.__module__)
    context = get_task_context(task)
    context.update(extra)
    logger.error(message, extra=context, exc_info=exc_info)
