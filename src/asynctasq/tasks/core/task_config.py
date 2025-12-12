"""Task configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field

from asynctasq.drivers import DriverType
from asynctasq.drivers.base_driver import BaseDriver


@dataclass(frozen=True, slots=True)
class TaskConfig:
    """Task execution configuration.

    Immutable configuration that ensures thread-safety and prevents accidental mutations.
    Use dataclasses.replace() to create modified copies.
    """

    queue: str = "default"
    max_retries: int = 3
    retry_delay: int = 60
    timeout: int | None = None
    driver_override: DriverType | BaseDriver | None = field(default=None, repr=False)
