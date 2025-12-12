"""Process pool management for CPU-bound task execution."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Global variables for warm event loop (set by process initializer)
_process_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None

# Metrics: Track fallback usage for observability
_fallback_count = 0
_fallback_lock = threading.Lock()


def init_warm_event_loop() -> None:
    """Initialize persistent event loop in subprocess (called by ProcessPoolExecutor initializer).

    Creates dedicated event loop in background thread to avoid overhead of creating new loop per task.
    """
    global _process_loop, _loop_thread

    # Create new event loop for this process
    _process_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_process_loop)

    # Run event loop in background thread
    _loop_thread = threading.Thread(target=_process_loop.run_forever, daemon=True)
    _loop_thread.start()

    logger.debug(
        "Warm event loop initialized in subprocess",
        extra={
            "thread_id": _loop_thread.ident,
            "loop_id": id(_process_loop),
        },
    )


def get_warm_event_loop() -> asyncio.AbstractEventLoop | None:
    """Get warm event loop for this process (None if not initialized or outside process pool)."""
    return _process_loop


def get_fallback_count() -> int:
    """Get asyncio.run() fallback count (high counts indicate missing warm_up() call)."""
    with _fallback_lock:
        return _fallback_count


def increment_fallback_count() -> int:
    """Increment and return fallback counter (thread-safe)."""
    global _fallback_count
    with _fallback_lock:
        _fallback_count += 1
        return _fallback_count


class ProcessPoolManager:
    """Singleton manager for sync and async process pools.

    Thread-safe with auto-initialization. Call warm_up() during worker startup to avoid initialization delays.
    """

    _sync_pool: ProcessPoolExecutor | None = None
    _sync_pool_size: int | None = None
    _sync_max_tasks_per_child: int | None = None

    _async_pool: ProcessPoolExecutor | None = None
    _async_pool_size: int | None = None
    _async_max_tasks_per_child: int | None = None

    _lock = threading.Lock()

    @classmethod
    def get_sync_pool(cls) -> ProcessPoolExecutor:
        """Get or auto-initialize sync process pool (thread-safe)."""
        with cls._lock:
            if cls._sync_pool is None:
                logger.warning(
                    "Sync process pool auto-initialized (consider explicit initialization in Worker.start())",
                    extra={"initialization_mode": "auto", "pool_type": "sync"},
                )
                cls._initialize_sync_unlocked()
                assert cls._sync_pool is not None
            return cls._sync_pool

    @classmethod
    def get_async_pool(cls) -> ProcessPoolExecutor:
        """Get or auto-initialize async process pool (thread-safe)."""
        with cls._lock:
            if cls._async_pool is None:
                logger.warning(
                    "Async process pool auto-initialized (consider explicit initialization in Worker.start())",
                    extra={"initialization_mode": "auto", "pool_type": "async"},
                )
                cls._initialize_async_unlocked(initializer=init_warm_event_loop)
                assert cls._async_pool is not None
            return cls._async_pool

    @classmethod
    def warm_up(
        cls,
        sync_max_workers: int | None = None,
        async_max_workers: int | None = None,
        sync_max_tasks_per_child: int | None = None,
        async_max_tasks_per_child: int | None = None,
    ) -> None:
        """Pre-initialize both pools to avoid ~50-100ms first-task delay."""
        logger.info(
            "Pre-warming process pools",
            extra={
                "sync_workers": sync_max_workers or os.cpu_count(),
                "async_workers": async_max_workers or os.cpu_count(),
            },
        )

        # Initialize sync pool
        cls.initialize_sync_pool(
            max_workers=sync_max_workers,
            max_tasks_per_child=sync_max_tasks_per_child,
        )

        # Initialize async pool with warm event loop
        cls.initialize_async_pool(
            max_workers=async_max_workers,
            max_tasks_per_child=async_max_tasks_per_child,
            initializer=init_warm_event_loop,
        )

        logger.info(
            "Process pools pre-warmed successfully",
            extra={"sync_pool_ready": True, "async_pool_ready": True},
        )

    @classmethod
    def initialize_sync_pool(
        cls,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
        mp_context: Any | None = None,
        initializer: Any | None = None,
        initargs: tuple[Any, ...] = (),
    ) -> None:
        """Initialize sync pool with custom config (thread-safe)."""
        with cls._lock:
            if cls._sync_pool is not None:
                logger.warning(
                    "Sync process pool already initialized, skipping",
                    extra={"pool_size": cls._sync_pool_size, "pool_type": "sync"},
                )
                return
            cls._initialize_sync_unlocked(
                max_workers=max_workers,
                max_tasks_per_child=max_tasks_per_child,
                mp_context=mp_context,
                initializer=initializer,
                initargs=initargs,
            )

    @classmethod
    def initialize_async_pool(
        cls,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
        mp_context: Any | None = None,
        initializer: Any | None = None,
        initargs: tuple[Any, ...] = (),
    ) -> None:
        """Initialize async pool with custom config (thread-safe, uses warm event loop by default)."""
        with cls._lock:
            if cls._async_pool is not None:
                logger.warning(
                    "Async process pool already initialized, skipping",
                    extra={"pool_size": cls._async_pool_size, "pool_type": "async"},
                )
                return

            # Use warm event loop initializer by default
            if initializer is None:
                initializer = init_warm_event_loop

            cls._initialize_async_unlocked(
                max_workers=max_workers,
                max_tasks_per_child=max_tasks_per_child,
                mp_context=mp_context,
                initializer=initializer,
                initargs=initargs,
            )

    @classmethod
    def _create_pool(
        cls,
        pool_type: str,
        max_workers: int,
        max_tasks_per_child: int | None,
        mp_context: Any | None,
        initializer: Any | None,
        initargs: tuple[Any, ...],
    ) -> ProcessPoolExecutor:
        """Create process pool with given configuration."""
        logger.info(
            f"{pool_type.capitalize()} process pool initialized",
            extra={
                "pool_size": max_workers,
                "max_tasks_per_child": max_tasks_per_child,
                "pool_type": pool_type,
            },
        )

        return ProcessPoolExecutor(
            max_workers=max_workers,
            max_tasks_per_child=max_tasks_per_child,
            mp_context=mp_context,
            initializer=initializer,
            initargs=initargs,
        )

    @classmethod
    def _initialize_sync_unlocked(
        cls,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
        mp_context: Any | None = None,
        initializer: Any | None = None,
        initargs: tuple[Any, ...] = (),
    ) -> None:
        """Internal sync pool initialization (assumes lock is held)."""
        max_workers = cls._validate_and_get_max_workers(max_workers)

        cls._sync_pool_size = max_workers
        cls._sync_max_tasks_per_child = max_tasks_per_child

        cls._sync_pool = cls._create_pool(
            pool_type="sync",
            max_workers=max_workers,
            max_tasks_per_child=max_tasks_per_child,
            mp_context=mp_context,
            initializer=initializer,
            initargs=initargs,
        )

    @classmethod
    def _initialize_async_unlocked(
        cls,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
        mp_context: Any | None = None,
        initializer: Any | None = None,
        initargs: tuple[Any, ...] = (),
    ) -> None:
        """Internal async pool initialization (assumes lock is held)."""
        max_workers = cls._validate_and_get_max_workers(max_workers)

        cls._async_pool_size = max_workers
        cls._async_max_tasks_per_child = max_tasks_per_child

        cls._async_pool = cls._create_pool(
            pool_type="async",
            max_workers=max_workers,
            max_tasks_per_child=max_tasks_per_child,
            mp_context=mp_context,
            initializer=initializer,
            initargs=initargs,
        )

    @classmethod
    def _validate_and_get_max_workers(cls, max_workers: int | None) -> int:
        """Validate and determine max_workers value."""
        # Determine max_workers
        if max_workers is None:
            max_workers = getattr(os, "process_cpu_count", os.cpu_count)() or 4
            assert max_workers is not None

        # Validate type and range
        if not isinstance(max_workers, int):
            raise TypeError(f"max_workers must be int, got {type(max_workers).__name__}")

        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")

        return max_workers

    @classmethod
    def shutdown_pools(cls, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shutdown both pools and free resources (thread-safe)."""
        with cls._lock:
            # Shutdown sync pool
            if cls._sync_pool is not None:
                logger.info(
                    "Shutting down sync process pool",
                    extra={
                        "wait": wait,
                        "cancel_futures": cancel_futures,
                        "pool_size": cls._sync_pool_size,
                        "pool_type": "sync",
                    },
                )
                try:
                    cls._sync_pool.shutdown(wait=wait, cancel_futures=cancel_futures)
                except Exception as e:
                    logger.exception(
                        "Error during sync process pool shutdown",
                        extra={"error": str(e), "error_type": type(e).__name__},
                    )
                    # Don't clear pool on error - allow retry
                    raise
                else:
                    # Only clear if shutdown succeeded
                    logger.info(
                        "Sync process pool shutdown complete",
                        extra={"status": "shutdown_complete", "pool_type": "sync"},
                    )
                    cls._sync_pool = None
                    cls._sync_pool_size = None
                    cls._sync_max_tasks_per_child = None

            # Shutdown async pool
            if cls._async_pool is not None:
                logger.info(
                    "Shutting down async process pool",
                    extra={
                        "wait": wait,
                        "cancel_futures": cancel_futures,
                        "pool_size": cls._async_pool_size,
                        "pool_type": "async",
                    },
                )
                try:
                    cls._async_pool.shutdown(wait=wait, cancel_futures=cancel_futures)
                except Exception as e:
                    logger.exception(
                        "Error during async process pool shutdown",
                        extra={"error": str(e), "error_type": type(e).__name__},
                    )
                    # Don't clear pool on error - allow retry
                    raise
                else:
                    # Only clear if shutdown succeeded
                    logger.info(
                        "Async process pool shutdown complete",
                        extra={"status": "shutdown_complete", "pool_type": "async"},
                    )
                    cls._async_pool = None
                    cls._async_pool_size = None
                    cls._async_max_tasks_per_child = None

            # Log if nothing to shutdown
            if cls._sync_pool is None and cls._async_pool is None:
                logger.debug(
                    "No process pools initialized, nothing to shutdown",
                    extra={"status": "not_initialized"},
                )

    @classmethod
    def get_stats(cls) -> dict[str, Any]:
        """Get pool statistics (size, status, max_tasks_per_child)."""
        with cls._lock:
            return {
                "sync": {
                    "status": "initialized" if cls._sync_pool is not None else "not_initialized",
                    "pool_size": cls._sync_pool_size,
                    "max_tasks_per_child": cls._sync_max_tasks_per_child,
                },
                "async": {
                    "status": "initialized" if cls._async_pool is not None else "not_initialized",
                    "pool_size": cls._async_pool_size,
                    "max_tasks_per_child": cls._async_max_tasks_per_child,
                },
            }

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if any pool is initialized (thread-safe)."""
        with cls._lock:
            return cls._sync_pool is not None or cls._async_pool is not None
