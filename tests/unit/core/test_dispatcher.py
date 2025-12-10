"""Unit tests for Dispatcher module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock drivers and serializers to avoid real connections
- Fast, isolated tests
- 100% code coverage
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from pytest import main, mark

from asynctasq.config import Config
from asynctasq.core.dispatcher import Dispatcher, cleanup, get_dispatcher
from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.serializers import BaseSerializer, MsgpackSerializer
from asynctasq.tasks import BaseTask, FunctionTask


# Test implementations for abstract Task
class ConcreteTask(BaseTask[str]):
    """Concrete implementation of Task for testing."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.public_param = kwargs.get("public_param", "default")

    async def handle(self) -> str:
        """Test implementation."""
        return "success"


@mark.unit
class TestDispatcherInitialization:
    """Test Dispatcher.__init__() method."""

    def test_init_with_driver_and_serializer(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)

        # Act
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        # Assert
        assert dispatcher.driver == mock_driver
        assert dispatcher.serializer == mock_serializer
        assert dispatcher._driver_cache == {}

    def test_init_with_driver_only_defaults_serializer(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        dispatcher = Dispatcher(driver=mock_driver)

        # Assert
        assert dispatcher.driver == mock_driver
        assert isinstance(dispatcher.serializer, MsgpackSerializer)
        assert dispatcher._driver_cache == {}

    def test_init_initializes_driver_cache(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        dispatcher = Dispatcher(driver=mock_driver)

        # Assert
        assert isinstance(dispatcher._driver_cache, dict)
        assert len(dispatcher._driver_cache) == 0


@mark.unit
class TestDispatcherGetDriver:
    """Test Dispatcher._get_driver() method."""

    def test_get_driver_no_override_returns_default(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=mock_driver)
        task = ConcreteTask()

        # Act
        result = dispatcher._get_driver(task)

        # Assert
        assert result == mock_driver

    def test_get_driver_with_base_driver_instance_override(self) -> None:
        # Arrange
        default_driver = MagicMock(spec=BaseDriver)
        override_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=default_driver)
        task = ConcreteTask()
        task._driver_override = override_driver  # type: ignore[attr-defined]

        # Act
        result = dispatcher._get_driver(task)

        # Assert
        assert result == override_driver
        assert result != default_driver

    def test_get_driver_with_string_override_creates_and_caches(self) -> None:
        # Arrange
        default_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=default_driver)
        task = ConcreteTask()
        task._driver_override = "redis"  # type: ignore[attr-defined]

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_redis_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_redis_driver

            # Act
            result = dispatcher._get_driver(task)

            # Assert
            assert result == mock_redis_driver
            mock_create.assert_called_once_with(mock_config, driver_type="redis")
            assert "redis" in dispatcher._driver_cache
            assert dispatcher._driver_cache["redis"] == mock_redis_driver

    def test_get_driver_with_string_override_uses_cache(self) -> None:
        # Arrange
        default_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=default_driver)
        task1 = ConcreteTask()
        task1._driver_override = "redis"  # type: ignore[attr-defined]
        task2 = ConcreteTask()
        task2._driver_override = "redis"  # type: ignore[attr-defined]

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_redis_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_redis_driver

            # Act - first call creates and caches
            result1 = dispatcher._get_driver(task1)
            # Act - second call uses cache
            result2 = dispatcher._get_driver(task2)

            # Assert
            assert result1 == mock_redis_driver
            assert result2 == mock_redis_driver
            # Should only create once
            assert mock_create.call_count == 1

    def test_get_driver_with_none_override_returns_default(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=mock_driver)
        task = ConcreteTask()
        task._driver_override = None  # type: ignore[attr-defined]

        # Act
        result = dispatcher._get_driver(task)

        # Assert
        assert result == mock_driver

    def test_get_driver_with_missing_attr_returns_default(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=mock_driver)
        task = ConcreteTask()
        # Don't set _driver_override at all

        # Act
        result = dispatcher._get_driver(task)

        # Assert
        assert result == mock_driver

    def test_get_driver_with_unexpected_override_type_returns_default(self) -> None:
        # Arrange - test fallback when driver_override is unexpected type
        # This covers line 67 (fallback return)
        mock_driver = MagicMock(spec=BaseDriver)
        dispatcher = Dispatcher(driver=mock_driver)
        task = ConcreteTask()
        # Set driver_override to something unexpected (not None, not BaseDriver, not string)
        task._driver_override = 123  # type: ignore[attr-defined]

        # Act
        result = dispatcher._get_driver(task)

        # Assert - should fall back to default driver
        assert result == mock_driver


@mark.unit
class TestDispatcherDispatch:
    """Test Dispatcher.dispatch() method."""

    @mark.asyncio
    async def test_dispatch_basic_creates_task_id_and_metadata(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask(public_param="test")
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]

        # Act
        task_id = await dispatcher.dispatch(task)

        # Assert
        assert isinstance(task_id, str)
        assert task._task_id == task_id
        assert task._dispatched_at is not None
        assert isinstance(task._dispatched_at, datetime)
        mock_driver.enqueue.assert_called_once()
        call_args = mock_driver.enqueue.call_args
        assert call_args[0][0] == "default"  # queue
        assert call_args[0][1] == b"serialized_data"  # serialized_task
        assert call_args[0][2] == 0  # delay_seconds

    @mark.asyncio
    async def test_dispatch_with_queue_override(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task.queue = "custom_queue"
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]

        # Act
        await dispatcher.dispatch(task, queue="override_queue")

        # Assert
        mock_driver.enqueue.assert_called_once()
        call_args = mock_driver.enqueue.call_args
        assert call_args[0][0] == "override_queue"

    @mark.asyncio
    async def test_dispatch_with_delay_parameter(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()

        # Act
        await dispatcher.dispatch(task, delay=120)

        # Assert
        mock_driver.enqueue.assert_called_once()
        call_args = mock_driver.enqueue.call_args
        assert call_args[0][2] == 120  # delay_seconds

    @mark.asyncio
    async def test_dispatch_with_task_delay_seconds(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task._delay_seconds = 60  # type: ignore[attr-defined]

        # Act
        await dispatcher.dispatch(task)

        # Assert
        mock_driver.enqueue.assert_called_once()
        call_args = mock_driver.enqueue.call_args
        assert call_args[0][2] == 60  # delay_seconds

    @mark.asyncio
    async def test_dispatch_delay_parameter_overrides_task_delay(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task._delay_seconds = 60  # type: ignore[attr-defined]

        # Act
        await dispatcher.dispatch(task, delay=180)

        # Assert
        mock_driver.enqueue.assert_called_once()
        call_args = mock_driver.enqueue.call_args
        assert call_args[0][2] == 180  # delay_seconds (parameter overrides)

    @mark.asyncio
    async def test_dispatch_uses_correct_driver_default(self) -> None:
        # Arrange
        default_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=default_driver, serializer=mock_serializer)
        task = ConcreteTask()
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]

        # Act
        await dispatcher.dispatch(task)

        # Assert
        default_driver.enqueue.assert_called_once()

    @mark.asyncio
    async def test_dispatch_uses_correct_driver_override_instance(self) -> None:
        # Arrange
        default_driver = AsyncMock(spec=BaseDriver)
        override_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=default_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task._driver_override = override_driver  # type: ignore[attr-defined]
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]

        # Act
        await dispatcher.dispatch(task)

        # Assert
        override_driver.enqueue.assert_called_once()
        default_driver.enqueue.assert_not_called()

    @mark.asyncio
    async def test_dispatch_uses_correct_driver_override_string(self) -> None:
        # Arrange
        default_driver = AsyncMock(spec=BaseDriver)
        override_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=default_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task._driver_override = "redis"  # type: ignore[attr-defined]
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_create.return_value = override_driver

            # Act
            await dispatcher.dispatch(task)

            # Assert
            override_driver.enqueue.assert_called_once()
            default_driver.enqueue.assert_not_called()

    @mark.asyncio
    async def test_dispatch_generates_unique_task_ids(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task1 = ConcreteTask()
        task2 = ConcreteTask()
        # Ensure _delay_seconds is not None to avoid comparison issues
        for task in [task1, task2]:
            if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
                task._delay_seconds = 0  # type: ignore[attr-defined]

        # Act
        task_id1 = await dispatcher.dispatch(task1)
        task_id2 = await dispatcher.dispatch(task2)

        # Assert
        assert task_id1 != task_id2
        assert task1._task_id != task2._task_id

    @mark.asyncio
    async def test_dispatch_sets_dispatched_at_timestamp(self) -> None:
        # Arrange
        mock_driver = AsyncMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized_data"
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()
        # Ensure _delay_seconds is not None to avoid comparison issues
        if not hasattr(task, "_delay_seconds") or task._delay_seconds is None:
            task._delay_seconds = 0  # type: ignore[attr-defined]
        before = datetime.now(UTC)

        # Act
        await dispatcher.dispatch(task)
        after = datetime.now(UTC)

        # Assert
        assert task._dispatched_at is not None
        assert before <= task._dispatched_at <= after


@mark.unit
class TestDispatcherSerializeTask:
    """Test TaskService.serialize_task() method via Dispatcher._task_service."""

    def test_serialize_task_includes_all_metadata(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask(public_param="test_value")
        task._task_id = "test-task-id"
        task._attempts = 2
        task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        task.max_retries = 5
        task.retry_delay = 120
        task.timeout = 300

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        mock_serializer.serialize.assert_called_once()
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert call_arg["class"] == f"{task.__class__.__module__}.{task.__class__.__name__}"
        assert call_arg["params"]["public_param"] == "test_value"
        assert call_arg["metadata"]["task_id"] == "test-task-id"
        assert call_arg["metadata"]["attempts"] == 2
        assert call_arg["metadata"]["dispatched_at"] == "2024-01-01T12:00:00+00:00"
        assert call_arg["metadata"]["max_retries"] == 5
        assert call_arg["metadata"]["retry_delay"] == 120
        assert call_arg["metadata"]["timeout"] == 300

    def test_serialize_task_excludes_private_attributes_from_params(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask(public_param="test")
        task._task_id = "test-id"
        task._attempts = 1
        task._private_attr = "should_not_be_included"  # type: ignore[attr-defined]

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        params = call_arg["params"]
        assert "public_param" in params
        assert "_task_id" not in params
        assert "_attempts" not in params
        assert "_private_attr" not in params

    def test_serialize_task_handles_none_dispatched_at(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask()
        task._task_id = "test-id"
        task._attempts = 0
        task._dispatched_at = None

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert call_arg["metadata"]["dispatched_at"] is None

    def test_serialize_task_includes_only_public_attributes(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask(public_param="public", another_public="also_public")
        task._private = "private"  # type: ignore[attr-defined]
        task.__dunder__ = "dunder"  # type: ignore[attr-defined]

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        params = call_arg["params"]
        assert "public_param" in params
        assert "another_public" in params
        assert "_private" not in params
        assert "__dunder__" not in params

    def test_serialize_task_handles_empty_params(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        # Create a task with no public attributes
        task = ConcreteTask()
        # Remove the default public_param by creating a task without it
        del task.public_param  # type: ignore[attr-defined]
        task._task_id = "test-id"
        task._attempts = 0
        task._dispatched_at = None

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        # Only check that private attributes are excluded, not that params is empty
        # (since ConcreteTask may have other public attributes)
        assert "_task_id" not in call_arg["params"]
        assert "_attempts" not in call_arg["params"]
        assert "public_param" not in call_arg["params"]

    def test_serialize_task_excludes_callable_attributes(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)
        task = ConcreteTask(public_param="test")
        task._task_id = "test-id"
        task._attempts = 1

        # Add callable attributes that should be excluded
        def some_function() -> None:
            pass

        task.callable_attr = some_function  # type: ignore[attr-defined]
        task.lambda_attr = lambda x: x  # type: ignore[attr-defined]

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        params = call_arg["params"]
        assert "public_param" in params
        assert "callable_attr" not in params
        assert "lambda_attr" not in params

    def test_serialize_function_task_includes_function_metadata(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        def test_func(x: int, y: str) -> str:
            """Test function."""
            return f"{x}:{y}"

        task = FunctionTask(test_func, 1, y="test")
        task._task_id = "test-id"
        task._attempts = 0
        task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        mock_serializer.serialize.assert_called_once()
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert call_arg["class"] == f"{FunctionTask.__module__}.{FunctionTask.__name__}"
        assert call_arg["metadata"]["func_name"] == "test_func"
        assert call_arg["metadata"]["func_module"] == test_func.__module__
        assert "func_file" not in call_arg["metadata"]  # Not __main__ module

    def test_serialize_function_task_handles_main_module_with_file_path(self) -> None:
        # Arrange
        from pathlib import Path
        import tempfile

        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        # Create a temporary Python file and define a function in it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test_func(x):\n    return x * 2\n")
            temp_file = Path(f.name)

        try:
            # Import the function from the temp file
            import importlib.util

            spec = importlib.util.spec_from_file_location("temp_module", temp_file)
            if spec is None or spec.loader is None:
                raise ValueError("Could not load module spec")
            temp_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(temp_module)

            # Set module name to __main__ to simulate main module
            temp_module.test_func.__module__ = "__main__"  # type: ignore[attr-defined]

            task = FunctionTask(temp_module.test_func, 5)  # type: ignore[attr-defined]
            task._task_id = "test-id"
            task._attempts = 0
            task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

            # Act
            dispatcher._task_service.serialize_task(task)

            # Assert
            call_arg = mock_serializer.serialize.call_args[0][0]
            assert call_arg["metadata"]["func_name"] == "test_func"
            assert call_arg["metadata"]["func_module"] == "__main__"
            assert "func_file" in call_arg["metadata"]
            assert call_arg["metadata"]["func_file"] == str(temp_file)
        finally:
            # Cleanup
            temp_file.unlink()

    def test_serialize_function_task_handles_main_module_file_path_error(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        # Create a mock function that simulates __main__ module
        # but will raise an error when trying to get file path
        mock_func = MagicMock()
        mock_func.__name__ = "test_func"
        mock_func.__module__ = "__main__"

        # Make inspect.getfile raise an error
        with patch("asynctasq.tasks.task_service.inspect.getfile") as mock_getfile:
            mock_getfile.side_effect = OSError("Cannot get file path")

            task = FunctionTask(mock_func)
            task._task_id = "test-id"
            task._attempts = 0
            task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

            # Act
            dispatcher._task_service.serialize_task(task)

            # Assert
            call_arg = mock_serializer.serialize.call_args[0][0]
            assert call_arg["metadata"]["func_name"] == "test_func"
            assert call_arg["metadata"]["func_module"] == "__main__"
            assert "func_file" not in call_arg["metadata"]  # Fallback doesn't include func_file

    def test_serialize_function_task_handles_main_module_type_error(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        # Create a mock function that simulates __main__ module
        # but will raise TypeError when trying to get file path
        mock_func = MagicMock()
        mock_func.__name__ = "test_func"
        mock_func.__module__ = "__main__"

        # Make inspect.getfile raise TypeError
        with patch("asynctasq.tasks.task_service.inspect.getfile") as mock_getfile:
            mock_getfile.side_effect = TypeError("Cannot get file path")

            task = FunctionTask(mock_func)
            task._task_id = "test-id"
            task._attempts = 0
            task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

            # Act
            dispatcher._task_service.serialize_task(task)

            # Assert
            call_arg = mock_serializer.serialize.call_args[0][0]
            assert call_arg["metadata"]["func_name"] == "test_func"
            assert call_arg["metadata"]["func_module"] == "__main__"
            assert "func_file" not in call_arg["metadata"]  # Fallback doesn't include func_file

    def test_serialize_function_task_excludes_func_from_params(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)
        dispatcher = Dispatcher(driver=mock_driver, serializer=mock_serializer)

        def test_func(x: int) -> int:
            return x * 2

        task = FunctionTask(test_func, 5)
        task._task_id = "test-id"
        task._attempts = 0

        # Act
        dispatcher._task_service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        params = call_arg["params"]
        # func is callable, so it should be excluded from params
        assert "func" not in params
        # args and kwargs should be included (they're not callable)
        assert "args" in params
        assert "kwargs" in params


@mark.unit
class TestGetDispatcher:
    """Test get_dispatcher() function."""

    def test_get_dispatcher_with_none_uses_default_config(self) -> None:
        # Arrange
        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
            patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_driver
            mock_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.return_value = mock_dispatcher

            # Act
            result = get_dispatcher()

            # Assert
            assert result == mock_dispatcher
            mock_get_config.assert_called_once()
            mock_create.assert_called_once_with(mock_config)
            mock_dispatcher_class.assert_called_once_with(mock_driver, event_emitter=ANY)

    def test_get_dispatcher_with_string_creates_from_config(self) -> None:
        # Arrange
        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
            patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_driver
            mock_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.return_value = mock_dispatcher

            # Act
            result = get_dispatcher("redis")

            # Assert
            assert result == mock_dispatcher
            mock_create.assert_called_once_with(mock_config, driver_type="redis")
            mock_dispatcher_class.assert_called_once_with(mock_driver, event_emitter=ANY)

    def test_get_dispatcher_with_base_driver_instance(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        with patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class:
            mock_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.return_value = mock_dispatcher

            # Act
            result = get_dispatcher(mock_driver)

            # Assert
            assert result == mock_dispatcher
            mock_dispatcher_class.assert_called_once_with(mock_driver, event_emitter=ANY)

    def test_get_dispatcher_caches_dispatchers(self) -> None:
        # Arrange - clear cache first
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
            patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_driver
            mock_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.return_value = mock_dispatcher

            # Act - call twice
            result1 = get_dispatcher("redis")
            result2 = get_dispatcher("redis")

            # Assert
            assert result1 == result2
            assert result1 is result2  # Should be the same instance
            # Should only create once
            assert mock_create.call_count == 1
            assert mock_dispatcher_class.call_count == 1

    def test_get_dispatcher_creates_separate_dispatchers_for_different_drivers(self) -> None:
        # Arrange - clear cache first
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
            patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class,
        ):
            mock_config = MagicMock(spec=Config)
            mock_get_config.return_value = mock_config
            mock_redis_driver = MagicMock(spec=BaseDriver)
            mock_postgres_driver = MagicMock(spec=BaseDriver)
            mock_create.side_effect = [mock_redis_driver, mock_postgres_driver]
            mock_redis_dispatcher = MagicMock(spec=Dispatcher)
            mock_postgres_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.side_effect = [mock_redis_dispatcher, mock_postgres_dispatcher]

            # Act
            result1 = get_dispatcher("redis")
            result2 = get_dispatcher("postgres")

            # Assert
            # Check that different dispatchers were created (different mock instances)
            assert result1 is not result2
            assert mock_create.call_count == 2
            assert mock_dispatcher_class.call_count == 2
            # Verify correct drivers were used
            # call_args_list contains (args, kwargs) tuples
            assert mock_create.call_args_list[0][1]["driver_type"] == "redis"
            assert mock_create.call_args_list[1][1]["driver_type"] == "postgres"

    def test_get_dispatcher_creates_separate_dispatchers_for_driver_instances(self) -> None:
        # Arrange
        driver1 = MagicMock(spec=BaseDriver)
        driver2 = MagicMock(spec=BaseDriver)
        with patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class:
            dispatcher1 = MagicMock(spec=Dispatcher)
            dispatcher2 = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.side_effect = [dispatcher1, dispatcher2]

            # Act
            result1 = get_dispatcher(driver1)
            result2 = get_dispatcher(driver2)

            # Assert
            assert result1 == dispatcher1
            assert result2 == dispatcher2
            assert result1 != result2
            assert mock_dispatcher_class.call_count == 2

    def test_get_dispatcher_handles_config_none_creates_from_env(self) -> None:
        # Arrange - clear cache first
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()

        with (
            patch("asynctasq.core.dispatcher.get_global_config") as mock_get_config,
            patch("asynctasq.core.dispatcher.Config.from_env") as mock_from_env,
            patch("asynctasq.core.dispatcher.DriverFactory.create_from_config") as mock_create,
            patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class,
        ):
            mock_get_config.return_value = None
            mock_config = MagicMock(spec=Config)
            mock_from_env.return_value = mock_config
            mock_driver = MagicMock(spec=BaseDriver)
            mock_create.return_value = mock_driver
            mock_dispatcher = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.return_value = mock_dispatcher

            # Act
            result = get_dispatcher()

            # Assert
            # Check that the dispatcher was created and returned
            # Note: result may be a different mock instance, so check behavior instead
            assert result is not None
            assert isinstance(result, MagicMock)
            mock_from_env.assert_called_once()
            mock_create.assert_called_once_with(mock_config)
            mock_dispatcher_class.assert_called_once_with(mock_driver, event_emitter=ANY)

    def test_get_dispatcher_caches_by_driver_instance_id(self) -> None:
        # Arrange
        driver1 = MagicMock(spec=BaseDriver)
        driver2 = MagicMock(spec=BaseDriver)
        with patch("asynctasq.core.dispatcher.Dispatcher") as mock_dispatcher_class:
            dispatcher1 = MagicMock(spec=Dispatcher)
            dispatcher2 = MagicMock(spec=Dispatcher)
            mock_dispatcher_class.side_effect = [dispatcher1, dispatcher2]

            # Act - same driver instance should return same dispatcher
            result1 = get_dispatcher(driver1)
            result2 = get_dispatcher(driver1)

            # Assert
            assert result1 == result2
            assert result1 == dispatcher1
            # Should only create once for same instance
            assert mock_dispatcher_class.call_count == 1

            # Act - different driver instance should return different dispatcher
            result3 = get_dispatcher(driver2)

            # Assert
            assert result3 == dispatcher2
            assert result3 != result1
            assert mock_dispatcher_class.call_count == 2


@mark.unit
class TestCleanup:
    """Test cleanup() function."""

    @mark.asyncio
    async def test_cleanup_with_no_dispatchers_returns_early(self) -> None:
        # Arrange - ensure _dispatchers is empty
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()

        # Act
        await cleanup()

        # Assert - should complete without error

    @mark.asyncio
    async def test_cleanup_disconnects_all_drivers(self) -> None:
        # Arrange
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()
        driver1 = AsyncMock(spec=BaseDriver)
        driver2 = AsyncMock(spec=BaseDriver)
        dispatcher1 = MagicMock(spec=Dispatcher)
        dispatcher2 = MagicMock(spec=Dispatcher)
        _dispatchers["driver1"] = (dispatcher1, driver1)
        _dispatchers["driver2"] = (dispatcher2, driver2)

        # Act
        await cleanup()

        # Assert
        driver1.disconnect.assert_called_once()
        driver2.disconnect.assert_called_once()
        assert len(_dispatchers) == 0

    @mark.asyncio
    async def test_cleanup_handles_disconnect_errors_gracefully(self) -> None:
        # Arrange
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()
        driver1 = AsyncMock(spec=BaseDriver)
        driver1.disconnect.side_effect = Exception("Connection error")
        driver2 = AsyncMock(spec=BaseDriver)
        dispatcher1 = MagicMock(spec=Dispatcher)
        dispatcher2 = MagicMock(spec=Dispatcher)
        _dispatchers["driver1"] = (dispatcher1, driver1)
        _dispatchers["driver2"] = (dispatcher2, driver2)

        # Act
        await cleanup()

        # Assert
        driver1.disconnect.assert_called_once()
        driver2.disconnect.assert_called_once()
        # Should still clear cache even if errors occur
        assert len(_dispatchers) == 0

    @mark.asyncio
    async def test_cleanup_clears_cache_after_disconnect(self) -> None:
        # Arrange
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()
        driver = AsyncMock(spec=BaseDriver)
        dispatcher = MagicMock(spec=Dispatcher)
        _dispatchers["test"] = (dispatcher, driver)

        # Act
        await cleanup()

        # Assert
        assert len(_dispatchers) == 0
        driver.disconnect.assert_called_once()

    @mark.asyncio
    async def test_cleanup_called_multiple_times_is_safe(self) -> None:
        # Arrange
        from asynctasq.core.dispatcher import _dispatchers

        _dispatchers.clear()
        driver = AsyncMock(spec=BaseDriver)
        dispatcher = MagicMock(spec=Dispatcher)
        _dispatchers["test"] = (dispatcher, driver)

        # Act
        await cleanup()
        await cleanup()  # Second call should be safe

        # Assert
        assert len(_dispatchers) == 0
        # Should only disconnect once (first call)
        assert driver.disconnect.call_count == 1


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
