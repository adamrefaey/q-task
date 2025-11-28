from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class TaskInfo:
    """
    Minimal task information returned by drivers.
    This is a simple dataclass (not Pydantic) to avoid dependencies.
    The monitor package will convert this to rich Pydantic Task models.
    """

    id: str
    name: str
    queue: str
    status: str  # "pending", "running", "completed", "failed", etc.
    enqueued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    worker_id: str | None = None
    attempt: int = 1
    max_retries: int = 3
    args: list[Any] | None = None
    kwargs: dict[str, Any] | None = None
    result: Any = None
    exception: str | None = None
    traceback: str | None = None
    priority: int = 0
    timeout_seconds: int | None = None
    tags: list[str] | None = None

    def __post_init__(self):
        if self.args is None:
            self.args = []
        if self.kwargs is None:
            self.kwargs = {}
        if self.tags is None:
            self.tags = []


@dataclass
class QueueStats:
    """Basic queue statistics from driver."""

    name: str
    depth: int  # pending tasks
    processing: int  # currently running
    completed_total: int = 0
    failed_total: int = 0
    avg_duration_ms: float | None = None
    throughput_per_minute: float | None = None


@dataclass
class WorkerInfo:
    """Basic worker information from driver."""

    worker_id: str
    status: str  # "active", "idle", "down"
    current_task_id: str | None = None
    tasks_processed: int = 0
    uptime_seconds: int = 0
    last_heartbeat: datetime | None = None
    load_percentage: float = 0.0
