"""Base task implementation with flexible execution strategies.

Provides foundation for all task types (AsyncTask, SyncTask, SyncProcessTask, AsyncProcessTask, FunctionTask).
Framework calls run() as entry point; subclasses implement run() with execution strategy; users implement execute().

See docs/task-definitions.md for task type selection guide.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Self

from asynctasq.tasks.core.task_config import TaskConfig

# Reserved parameter names that would shadow task methods/attributes
RESERVED_NAMES = frozenset(
    {
        "config",
        "run",
        "execute",
        "dispatch",
        "failed",
        "should_retry",
        "on_queue",
        "delay",
        "retry_after",
    }
)


class BaseTask[T](ABC):
    """Abstract base class for all task types.

    Provides task configuration, dispatch, retry logic, and lifecycle hooks.
    Subclasses implement run() (execution strategy); users implement execute() (business logic).
    """

    # Delay configuration (separate from TaskConfig for runtime flexibility)
    _delay_seconds: int | None = None

    @classmethod
    def _get_additional_reserved_names(cls) -> frozenset[str]:
        """Hook for subclasses to add additional reserved names.

        Returns:
            Set of additional reserved parameter names
        """
        return frozenset()

    @classmethod
    def _extract_config_from_class(cls) -> dict[str, Any]:
        """Extract TaskConfig values from class attributes for initialization."""
        return {
            "queue": getattr(cls, "queue", "default"),
            "max_retries": getattr(cls, "max_retries", 3),
            "retry_delay": getattr(cls, "retry_delay", 60),
            "timeout": getattr(cls, "timeout", None),
        }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize task with parameters.

        Args:
            **kwargs: Task parameters (become instance attributes)

        Raises:
            ValueError: If parameter name is reserved or starts with underscore
        """
        # Initialize configuration from class attributes if present
        # This supports the pattern: class MyTask: queue = "custom"
        config_values = self._extract_config_from_class()
        self.config = TaskConfig(**config_values)

        # Combine base reserved names with subclass-specific ones
        all_reserved = RESERVED_NAMES | self._get_additional_reserved_names()

        for key, value in kwargs.items():
            if key.startswith("_"):
                raise ValueError(
                    f"Parameter name '{key}' is reserved for internal use. "
                    f"Task parameters cannot start with underscore."
                )
            if key in all_reserved:
                raise ValueError(
                    f"Parameter name '{key}' is a reserved name that would "
                    f"shadow a task method or attribute. Choose a different name."
                )
            setattr(self, key, value)

        # Metadata (managed internally by dispatcher/worker)
        self._task_id: str | None = None
        self._attempts: int = 0
        self._dispatched_at: datetime | None = None

    async def failed(self, exception: Exception) -> None:  # noqa: B027
        """Hook called when task fails after exhausting retries.

        Override to implement alerting, cleanup, compensation, or custom logging.
        Exceptions raised here are logged but don't affect task processing.
        Keep idempotent (may be called multiple times on worker restart).

        Args:
            exception: Exception that caused the final failure

        Example:
            ```python
            async def failed(self, exception: Exception) -> None:
                await alert_team(f"Task {self._task_id} failed: {exception}")
                await rollback_transaction(self.transaction_id)
            ```
        """
        ...

    def should_retry(self, exception: Exception) -> bool:
        """Hook to determine if task should retry after exception.

        Override to implement custom retry logic (e.g., fail fast on validation errors, retry only network errors).
        Combined with max_retries limit (both must be True to retry).

        Args:
            exception: Exception that occurred

        Returns:
            True to retry, False to fail immediately (default: True)

        Example:
            ```python
            def should_retry(self, exception: Exception) -> bool:
                if isinstance(exception, (ValueError, ValidationError)):
                    return False  # Don't retry business logic errors
                return isinstance(exception, (ConnectionError, TimeoutError))
            ```
        """
        return True

    @abstractmethod
    async def run(self) -> T:
        """Execute task (framework entry point).

        Subclasses implement execution strategy. Framework calls this from TaskExecutor with timeout wrapper.
        Users implement execute() with business logic.

        Returns:
            Task result
        """
        ...

    def on_queue(self, queue_name: str) -> Self:
        """Set queue for task dispatch (method chaining).

        Args:
            queue_name: Queue name

        Returns:
            Self for chaining

        Warning:
            Mutates task instance. Subsequent dispatch() calls use modified config.
        """
        self.config.queue = queue_name
        return self

    def delay(self, seconds: int) -> Self:
        """Set execution delay (method chaining).

        Args:
            seconds: Delay in seconds

        Returns:
            Self for chaining

        Warning:
            Mutates task instance. Applied to all subsequent dispatch() calls.
        """
        self._delay_seconds = seconds
        return self

    def retry_after(self, seconds: int) -> Self:
        """Set retry delay (method chaining).

        Args:
            seconds: Retry delay in seconds

        Returns:
            Self for chaining

        Warning:
            Mutates task instance. Applied to all subsequent dispatch() calls.
        """
        self.config.retry_delay = seconds
        return self

    async def dispatch(self) -> str:
        """Dispatch task to queue for async execution.

        Returns:
            Task ID
        """
        from asynctasq.core.dispatcher import get_dispatcher

        # Pass driver override to get_dispatcher if set
        driver_override = self.config.driver_override
        return await get_dispatcher(driver_override).dispatch(self)
