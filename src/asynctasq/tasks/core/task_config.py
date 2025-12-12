"""Task configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field

from asynctasq.drivers import DriverType
from asynctasq.drivers.base_driver import BaseDriver


@dataclass
class TaskConfig:
    """Task execution configuration.

    Mutable to support fluent API (e.g., task.on_queue().dispatch()).
    """

    queue: str = "default"
    max_retries: int = 3
    retry_delay: int = 60
    timeout: int | None = None
    driver_override: DriverType | BaseDriver | None = field(default=None, repr=False)
