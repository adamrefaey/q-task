"""Unit tests for FastAPI integration.

Testing Strategy:
- Mock FastAPI and async context manager behavior
- Test lifespan context manager startup/shutdown
- Test dependency injection methods
- Test configuration options
"""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest import fixture, mark, raises

from q_task.config import Config
from q_task.core.dispatcher import Dispatcher
from q_task.drivers.base_driver import BaseDriver
from q_task.drivers.redis_driver import RedisDriver
from q_task.integrations.fastapi import AsyncTaskIntegration


@fixture
def mock_driver() -> BaseDriver:
    """Create a mock driver for testing."""
    driver = MagicMock(spec=BaseDriver)
    driver.connect = AsyncMock()
    driver.disconnect = AsyncMock()
    return driver


@fixture
def mock_fastapi_app():
    """Create a mock FastAPI app for testing."""
    app = MagicMock()
    return app


class TestAsyncTaskIntegration:
    """Test AsyncTaskIntegration class."""

    @mark.asyncio
    async def test_init_with_config(self, mock_driver):
        """Test initialization with explicit config."""
        config = Config(driver="redis")
        integration = AsyncTaskIntegration(config=config)

        assert integration._config == config
        assert integration._driver is None
        assert integration._dispatcher is None
        assert not integration._initialized

    @mark.asyncio
    async def test_init_with_driver(self, mock_driver):
        """Test initialization with explicit driver."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        assert integration._config is None
        assert integration._driver == mock_driver
        assert integration._dispatcher is None
        assert not integration._initialized

    @mark.asyncio
    async def test_init_without_args(self):
        """Test initialization without arguments (uses global config)."""
        integration = AsyncTaskIntegration()

        assert integration._config is None
        assert integration._driver is None
        assert integration._dispatcher is None
        assert not integration._initialized

    @mark.asyncio
    async def test_lifespan_startup_and_shutdown(self, mock_driver, mock_fastapi_app):
        """Test lifespan context manager startup and shutdown."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        # Enter lifespan context (startup)
        async with integration.lifespan(mock_fastapi_app):
            # Verify startup
            assert integration._initialized
            assert integration._dispatcher is not None
            assert integration._dispatcher.driver == mock_driver
            mock_driver.connect.assert_called_once()

        # Verify shutdown
        assert not integration._initialized
        assert integration._dispatcher is None
        mock_driver.disconnect.assert_called_once()

    @mark.asyncio
    async def test_lifespan_with_config(self, mock_fastapi_app):
        """Test lifespan with config (creates driver from config)."""
        config = Config(driver="redis")
        integration = AsyncTaskIntegration(config=config)

        with patch("q_task.integrations.fastapi.DriverFactory.create_from_config") as mock_factory:
            mock_driver = RedisDriver()
            mock_factory.return_value = mock_driver

            async with integration.lifespan(mock_fastapi_app):
                assert integration._initialized
                assert integration._dispatcher is not None
                mock_factory.assert_called_once_with(config)

    @mark.asyncio
    async def test_lifespan_without_config(self, mock_fastapi_app):
        """Test lifespan without config (uses global config)."""
        integration = AsyncTaskIntegration()

        with (
            patch("q_task.integrations.fastapi.get_global_config") as mock_get_config,
            patch("q_task.integrations.fastapi.DriverFactory.create_from_config") as mock_factory,
        ):
            config = Config(driver="redis")
            mock_get_config.return_value = config
            mock_driver = RedisDriver()
            mock_factory.return_value = mock_driver

            async with integration.lifespan(mock_fastapi_app):
                assert integration._initialized
                mock_get_config.assert_called_once()
                mock_factory.assert_called_once_with(config)

    @mark.asyncio
    async def test_get_dispatcher_success(self, mock_driver, mock_fastapi_app):
        """Test get_dispatcher returns dispatcher after initialization."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        async with integration.lifespan(mock_fastapi_app):
            dispatcher = integration.get_dispatcher()
            assert isinstance(dispatcher, Dispatcher)
            assert dispatcher.driver == mock_driver

    @mark.asyncio
    async def test_get_dispatcher_before_init(self):
        """Test get_dispatcher raises error before initialization."""
        integration = AsyncTaskIntegration()

        with raises(RuntimeError, match="not initialized"):
            integration.get_dispatcher()

    @mark.asyncio
    async def test_get_driver_success(self, mock_driver, mock_fastapi_app):
        """Test get_driver returns driver after initialization."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        async with integration.lifespan(mock_fastapi_app):
            driver = integration.get_driver()
            assert driver == mock_driver

    @mark.asyncio
    async def test_get_driver_before_init(self):
        """Test get_driver raises error before initialization."""
        integration = AsyncTaskIntegration()

        with raises(RuntimeError, match="not initialized"):
            integration.get_driver()

    @mark.asyncio
    async def test_lifespan_idempotent_startup(self, mock_driver, mock_fastapi_app):
        """Test that startup is idempotent (can be called multiple times safely)."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        async with integration.lifespan(mock_fastapi_app):
            # Call startup again (should be no-op)
            await integration._startup()
            await integration._startup()

            # Should only connect once
            assert mock_driver.connect.call_count == 1

    @mark.asyncio
    async def test_lifespan_idempotent_shutdown(self, mock_driver, mock_fastapi_app):
        """Test that shutdown is idempotent (can be called multiple times safely)."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        async with integration.lifespan(mock_fastapi_app):
            pass

        # Call shutdown again (should be no-op)
        await integration._shutdown()
        await integration._shutdown()

        # Should only disconnect once
        assert mock_driver.disconnect.call_count == 1

    @mark.asyncio
    async def test_lifespan_exception_handling(self, mock_driver, mock_fastapi_app):
        """Test that shutdown is called even if exception occurs in lifespan."""
        integration = AsyncTaskIntegration(driver=mock_driver)

        with raises(ValueError):
            async with integration.lifespan(mock_fastapi_app):
                raise ValueError("Test exception")

        # Shutdown should still be called
        mock_driver.disconnect.assert_called_once()
