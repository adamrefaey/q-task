"""ProcessTask - CPU-bound task execution using ProcessPoolExecutor.

This module provides ProcessTask, a specialized Task class for CPU-intensive workloads
that need true multiprocessing to bypass Python's Global Interpreter Lock (GIL).

Key Features:
- True multi-core parallelism via ProcessPoolExecutor
- Async integration using asyncio.run_in_executor
- Class-level process pool lifecycle management
- Automatic process recycling to prevent memory leaks (Python 3.11+)
- Pickling validation for arguments and return values

Best Practices Applied (2024-2025):
- Use os.process_cpu_count() for default worker count (Python 3.13+)
- Implement max_tasks_per_child for process recycling
- Support custom mp_context for control over start method
- Provide initializer/initargs for per-process setup
- Graceful shutdown with proper pool cleanup
- Clear separation between sync execution logic and async wrapper

Performance:
- Ideal for CPU-bound tasks with >80% CPU utilization
- Bypasses GIL for true parallel execution
- Higher overhead than ThreadPoolExecutor (~50ms per task)
- Best for tasks taking >100ms to complete

Limitations:
- Arguments and return values must be picklable
- No shared memory between processes (use multiprocessing.Manager if needed)
- Higher memory footprint (each process has its own Python interpreter)
- Not suitable for I/O-bound tasks (use Task or SyncTask instead)

Example:
    class HeavyCPUTask(ProcessTask):
        def handle_process(self, n: int) -> int:
            # Runs in separate process with independent GIL
            import math
            result = 1
            for i in range(1, n + 1):
                result *= i
            return result

    # Dispatch task
    task_id = await HeavyCPUTask(n=10000).dispatch()
""" 

from __future__ import annotations

from abc import abstractmethod
import asyncio
from concurrent.futures import ProcessPoolExecutor
import logging
import os
from typing import Any

from .task import Task

logger = logging.getLogger(__name__)


class ProcessTask[T](Task[T]):
    """Base class for CPU-bound tasks requiring true multiprocessing.

    ProcessTask uses ProcessPoolExecutor to execute tasks in separate processes,
    each with its own Python interpreter and independent Global Interpreter Lock.
    This enables true multi-core parallelism for CPU-intensive workloads.

    ## When to Use

    Use ProcessTask for:
    - Heavy computation (>80% CPU utilization)
    - Data processing, scientific computing, ML inference
    - Image/video processing, encoding/decoding
    - Cryptographic operations
    - Any task that would block the event loop for >100ms

    ## When NOT to Use

    Don't use ProcessTask for:
    - I/O-bound tasks (network, file I/O) - use Task instead
    - Light CPU work (<50% CPU) - use Task or SyncTask
    - Tasks requiring shared mutable state - processes are isolated
    - Tasks with unpicklable arguments/returns - serialization will fail

    ## Process Pool Lifecycle

    The process pool is shared across all ProcessTask instances:
    1. Initialized on first task execution or explicit call to initialize_pool()
    2. Workers are reused across multiple task executions
    3. Automatically cleaned up on worker shutdown (graceful termination)
    4. Processes recycled after max_tasks_per_child tasks (if configured)

    ## Architecture

    - Class-level process pool (shared across all ProcessTask instances)
    - Async wrapper (execute) delegates to sync handle() in subprocess
    - Each subprocess runs handle() with independent GIL
    - Results serialized via pickle and returned to main process

    ## Performance Tuning

    Pool sizing (default: os.process_cpu_count() or 4):
    - CPU-only workload: match core count (cpu_count)
    - Mixed CPU+I/O: add 1-2 extra workers (cpu_count + 1)
    - Shared machine: reduce to avoid contention

    Process recycling (Python 3.11+):
    - Set max_tasks_per_child=100-1000 to prevent memory leaks
    - Lower values = more overhead but better memory hygiene
    - Higher values = better performance but potential memory growth

    ## Attributes

        _process_pool: Class-level ProcessPoolExecutor instance (shared)
        _pool_size: Number of worker processes in the pool
        _max_tasks_per_child: Max tasks per worker before recycling (None = unlimited)

    ## Thread Safety

    ProcessTask.initialize_pool() and shutdown_pool() are NOT thread-safe.
    These should only be called from the main thread (e.g., worker startup/shutdown).
    Task execution (execute/handle) is thread-safe once pool is initialized.
    """

    # Class-level process pool (shared across all ProcessTask instances)
    _process_pool: ProcessPoolExecutor | None = None
    _pool_size: int | None = None
    _max_tasks_per_child: int | None = None

    @classmethod
    def initialize_pool(
        cls,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
        mp_context: Any | None = None,
        initializer: Any | None = None,
        initargs: tuple[Any, ...] = (),
    ) -> None:
        """Initialize the process pool for CPU-bound task execution.

        This method should be called once during worker startup. If not called
        explicitly, the pool will be auto-initialized on first task execution.

        Args:
            max_workers: Number of worker processes. If None, defaults to
                os.process_cpu_count() (Python 3.13+) or os.cpu_count() or 4.
            max_tasks_per_child: Maximum tasks a worker can execute before being
                recycled. Recommended: 100-1000 to prevent memory leaks. None means
                workers live until pool shutdown. Requires Python 3.11+.
            mp_context: Multiprocessing context (spawn/fork/forkserver). If None,
                uses default. Recommended: 'spawn' for safety on multi-threaded apps.
            initializer: Callable run once when each worker process starts.
                Useful for setting up per-process resources (DB connections, etc).
            initargs: Arguments passed to initializer function.

        Raises:
            RuntimeError: If pool is already initialized

        Example:
            # Basic initialization (defaults)
            ProcessTask.initialize_pool()

            # Custom sizing and recycling
            ProcessTask.initialize_pool(
                max_workers=8,
                max_tasks_per_child=500
            )

            # With per-process initialization
            def setup_worker():
                import numpy as np
                np.random.seed()  # Re-seed RNG in each process

            ProcessTask.initialize_pool(
                max_workers=4,
                initializer=setup_worker
            )

            # Force spawn method (safer for multi-threaded apps)
            import multiprocessing
            ProcessTask.initialize_pool(
                mp_context=multiprocessing.get_context('spawn')
            )
        """
        if cls._process_pool is not None:
            logger.warning("ProcessTask pool already initialized, skipping re-initialization")
            return

        # Determine worker count
        if max_workers is None:
            # Use process_cpu_count (Python 3.13+) with fallback to cpu_count
            max_workers = getattr(os, "process_cpu_count", os.cpu_count)() or 4

        cls._pool_size = max_workers
        cls._max_tasks_per_child = max_tasks_per_child

        logger.info(
            f"Initializing ProcessTask pool: max_workers={max_workers}, "
            f"max_tasks_per_child={max_tasks_per_child}"
        )

        # Create pool with configuration
        cls._process_pool = ProcessPoolExecutor(
            max_workers=max_workers,
            max_tasks_per_child=max_tasks_per_child,
            mp_context=mp_context,
            initializer=initializer,
            initargs=initargs,
        )

        logger.info("ProcessTask pool initialized successfully")

    @classmethod
    def shutdown_pool(cls, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shutdown the process pool and free resources.

        This method should be called during worker shutdown to ensure proper cleanup.
        It will wait for pending tasks to complete (if wait=True) before terminating
        worker processes.

        Args:
            wait: If True, block until all pending tasks complete. If False,
                shutdown immediately and terminate workers. Recommended: True for
                graceful shutdown.
            cancel_futures: If True, cancel all pending futures that haven't
                started executing. Requires wait=True to be meaningful.

        Example:
            # Graceful shutdown (wait for in-flight tasks)
            ProcessTask.shutdown_pool(wait=True)

            # Immediate shutdown (force terminate)
            ProcessTask.shutdown_pool(wait=False)

            # Cancel pending + wait for running
            ProcessTask.shutdown_pool(wait=True, cancel_futures=True)
        """
        if cls._process_pool is None:
            logger.debug("ProcessTask pool not initialized, nothing to shutdown")
            return

        logger.info(
            f"Shutting down ProcessTask pool (wait={wait}, cancel_futures={cancel_futures})"
        )

        try:
            cls._process_pool.shutdown(wait=wait, cancel_futures=cancel_futures)
            logger.info("ProcessTask pool shutdown complete")
        except Exception as e:
            logger.exception(f"Error during ProcessTask pool shutdown: {e}")
        finally:
            cls._process_pool = None
            cls._pool_size = None
            cls._max_tasks_per_child = None

    async def execute(self) -> T:
        """Execute task in process pool with async wrapper.

        This method is the internal entry point for ProcessTask execution.
        It auto-initializes the pool if needed and delegates to run_in_executor.

        Returns:
            Task result (must be picklable)

        Raises:
            RuntimeError: If pool initialization fails
            TypeError: If arguments or return value are not picklable
            Exception: Any exception raised by handle_process() method
        """
        # Auto-initialize pool if not already done
        if ProcessTask._process_pool is None:
            logger.debug("Auto-initializing ProcessTask pool (first execution)")
            ProcessTask.initialize_pool()

        # Get current event loop
        loop = asyncio.get_running_loop()

        # Run handle_process() in process pool and await result
        try:
            result = await loop.run_in_executor(self._process_pool, self._run_in_process)
            return result
        except Exception as e:
            logger.exception(
                f"ProcessTask execution failed: {e}",
                extra={
                    "task_id": self._task_id,
                    "task_class": self.__class__.__name__,
                    "attempts": self._attempts,
                },
            )
            raise

    def _run_in_process(self) -> T:
        """Wrapper for subprocess execution.

        This method runs in the worker subprocess (not the main process).
        It calls the user-defined handle_process() method and returns the result.

        Returns:
            Task result from handle_process() method
        """
        # This executes in the subprocess with independent GIL
        return self.handle_process()

    async def handle(self) -> T:
        """Async wrapper that delegates to execute() for ProcessTask.

        This method overrides Task.handle() to integrate with the worker's
        async execution flow. The actual work happens in handle_process()
        which runs in a subprocess.

        Returns:
            Task result from subprocess execution
        """
        return await self.execute()

    @abstractmethod
    def handle_process(self) -> T:
        """Execute the CPU-bound task logic in a subprocess.

        Override this method with your CPU-intensive work. This method runs
        in a separate process with its own Python interpreter and independent
        Global Interpreter Lock (GIL).

        Important:
        - All arguments (self attributes) must be picklable
        - Return value must be picklable
        - No shared memory with parent process
        - Each execution may run in a different process
        - Avoid heavy initialization - use pool initializer instead

        Returns:
            Task result (must be picklable)

        Example:
            class FactorialTask(ProcessTask):
                def handle_process(self) -> int:
                    n = self.n  # Retrieved from task attributes
                    result = 1
                    for i in range(1, n + 1):
                        result *= i
                    return result
        """
        pass
