"""FastAPI integration for async_task.

Provides seamless integration with FastAPI applications through lifespan management
and dependency injection.
"""

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from ..config import Config, get_global_config
from ..core.dispatcher import Dispatcher
from ..core.driver_factory import DriverFactory
from ..drivers.base_driver import BaseDriver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class AsyncTaskIntegration:
    """FastAPI integration for async_task.

    Manages the lifecycle of queue drivers and dispatchers within FastAPI applications.
    Handles connection setup on startup and cleanup on shutdown.

    Example:
        ```python
        from fastapi import FastAPI
        from async_task.integrations.fastapi import AsyncTaskIntegration

        # Auto-configure from environment variables
        async_task = AsyncTaskIntegration()
        app = FastAPI(lifespan=async_task.lifespan)

        # Or with explicit configuration
        from async_task.config import Config
        config = Config(driver="redis", redis_url="redis://localhost:6379")
        async_task = AsyncTaskIntegration(config=config)
        app = FastAPI(lifespan=async_task.lifespan)
        ```
    """

    def __init__(
        self,
        config: Config | None = None,
        driver: BaseDriver | None = None,
    ) -> None:
        """Initialize FastAPI integration.

        Args:
            config: Optional configuration. If None, uses global config or loads from environment.
            driver: Optional driver instance. If provided, uses this driver instead of creating one.

        Note:
            If both `config` and `driver` are provided, `driver` takes precedence.
            If neither is provided, loads configuration from environment variables.
        """
        self._config = config
        self._driver = driver
        self._dispatcher: Dispatcher | None = None
        self._initialized = False

    @asynccontextmanager
    async def lifespan(self, app: "FastAPI") -> "AsyncGenerator[None, None]":
        """FastAPI lifespan context manager.

        Handles startup and shutdown of queue drivers:
        - Startup: Initializes configuration, creates driver, connects to backend
        - Shutdown: Disconnects driver and cleans up resources

        Args:
            app: FastAPI application instance

        Yields:
            None (control returns to FastAPI during app lifetime)
        """
        # Startup
        await self._startup()

        try:
            yield
        finally:
            # Shutdown
            await self._shutdown()

    async def _startup(self) -> None:
        """Initialize driver and dispatcher on FastAPI startup."""
        if self._initialized:
            return

        try:
            # Determine configuration
            if self._driver is not None:
                # Use provided driver instance
                driver = self._driver
            elif self._config is not None:
                # Use provided config to create driver
                driver = DriverFactory.create_from_config(self._config)
            else:
                # Use global config or load from environment
                config = get_global_config()
                driver = DriverFactory.create_from_config(config)

            # Connect driver
            await driver.connect()
            logger.info(f"Connected to queue driver: {driver.__class__.__name__}")

            # Create dispatcher
            self._dispatcher = Dispatcher(driver)
            self._initialized = True
            logger.info("FastAPI integration initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize FastAPI integration: {e}", exc_info=True)
            raise

    async def _shutdown(self) -> None:
        """Cleanup driver and dispatcher on FastAPI shutdown."""
        if not self._initialized or self._dispatcher is None:
            return

        try:
            # Disconnect driver
            await self._dispatcher.driver.disconnect()
            logger.info("Disconnected from queue driver")
        except Exception as e:
            logger.error(f"Error during FastAPI integration shutdown: {e}", exc_info=True)
        finally:
            self._dispatcher = None
            self._initialized = False

    def get_dispatcher(self) -> Dispatcher:
        """Get the dispatcher instance for dependency injection.

        Returns:
            Dispatcher instance

        Raises:
            RuntimeError: If integration has not been initialized (app not started)

        Note:
            This returns the dispatcher managed by this integration instance.
            Tasks using `task.dispatch()` will use the global dispatcher system,
            which may create a separate dispatcher. For consistency, consider
            using this dispatcher directly via dependency injection.

        Example:
            ```python
            from fastapi import Depends
            from async_task.integrations.fastapi import AsyncTaskIntegration

            async_task = AsyncTaskIntegration()
            app = FastAPI(lifespan=async_task.lifespan)

            @app.post("/dispatch")
            async def dispatch_task(
                dispatcher: Dispatcher = Depends(async_task.get_dispatcher)
            ):
                # Use dispatcher to dispatch tasks directly
                task_id = await dispatcher.dispatch(my_task)
                return {"task_id": task_id}
            ```
        """
        if not self._initialized or self._dispatcher is None:
            raise RuntimeError(
                "AsyncTaskIntegration not initialized. "
                "Ensure FastAPI app has started (lifespan context entered)."
            )
        return self._dispatcher

    def get_driver(self) -> BaseDriver:
        """Get the driver instance for dependency injection.

        Returns:
            BaseDriver instance

        Raises:
            RuntimeError: If integration has not been initialized (app not started)

        Example:
            ```python
            from fastapi import Depends
            from async_task.integrations.fastapi import AsyncTaskIntegration

            async_task = AsyncTaskIntegration()
            app = FastAPI(lifespan=async_task.lifespan)

            @app.get("/queue-stats")
            async def get_stats(
                driver: BaseDriver = Depends(async_task.get_driver)
            ):
                size = await driver.get_queue_size("default")
                return {"queue_size": size}
            ```
        """
        if not self._initialized or self._dispatcher is None:
            raise RuntimeError(
                "AsyncTaskIntegration not initialized. "
                "Ensure FastAPI app has started (lifespan context entered)."
            )
        return self._dispatcher.driver
