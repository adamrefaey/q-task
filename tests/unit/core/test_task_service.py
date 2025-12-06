"""Unit tests for TaskService module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock drivers and serializers to avoid real connections
- Fast, isolated tests
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pytest import main, mark, raises

from asynctasq.core.models import TaskInfo
from asynctasq.core.task import FunctionTask, Task
from asynctasq.core.task_service import TaskService
from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.serializers.base_serializer import BaseSerializer
from asynctasq.serializers.msgpack_serializer import MsgpackSerializer


# Test implementations for abstract Task
class ConcreteTask(Task[str]):
    """Concrete implementation of Task for testing."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.public_param = kwargs.get("public_param", "default")

    async def handle(self) -> str:
        """Test implementation."""
        return "success"


class FailingTask(Task[str]):
    """Task that always fails for testing retry logic."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    async def handle(self) -> str:
        raise ValueError("Task failed")


@mark.unit
class TestTaskServiceInitialization:
    """Test TaskService.__init__() method."""

    def test_init_with_serializer(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)

        # Act
        service = TaskService(serializer=mock_serializer)

        # Assert
        assert service.serializer == mock_serializer
        assert service.driver is None

    def test_init_with_driver(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        service = TaskService(driver=mock_driver)

        # Assert
        assert service.driver == mock_driver
        assert isinstance(service.serializer, MsgpackSerializer)

    def test_init_defaults_serializer_to_msgpack(self) -> None:
        # Act
        service = TaskService()

        # Assert
        assert isinstance(service.serializer, MsgpackSerializer)

    def test_init_with_all_parameters(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        service = TaskService(serializer=mock_serializer, driver=mock_driver)

        # Assert
        assert service.serializer == mock_serializer
        assert service.driver == mock_driver


@mark.unit
class TestTaskServiceSerializeTask:
    """Test TaskService.serialize_task() method."""

    def test_serialize_task_includes_class_path(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)
        task = ConcreteTask()
        task._task_id = "test-id"
        task._attempts = 0

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert "class" in call_arg
        assert "ConcreteTask" in call_arg["class"]

    def test_serialize_task_includes_metadata(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)
        task = ConcreteTask()
        task._task_id = "test-id-123"
        task._attempts = 2
        task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        task.max_retries = 5
        task.retry_delay = 30
        task.timeout = 300
        task.queue = "test_queue"

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        metadata = call_arg["metadata"]
        assert metadata["task_id"] == "test-id-123"
        assert metadata["attempts"] == 2
        assert metadata["max_retries"] == 5
        assert metadata["retry_delay"] == 30
        assert metadata["timeout"] == 300
        assert metadata["queue"] == "test_queue"
        assert "2024-01-01" in metadata["dispatched_at"]

    def test_serialize_task_excludes_private_attributes(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)
        task = ConcreteTask(public_param="visible")
        task._task_id = "test-id"
        task._private_attr = "hidden"  # type: ignore[attr-defined]

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert "public_param" in call_arg["params"]
        assert "_private_attr" not in call_arg["params"]
        assert "_task_id" not in call_arg["params"]

    def test_serialize_task_excludes_callable_attributes(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)
        task = ConcreteTask()
        task._task_id = "test-id"
        task.some_method = lambda: None  # type: ignore[attr-defined]

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert "some_method" not in call_arg["params"]

    def test_serialize_task_handles_none_dispatched_at(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)
        task = ConcreteTask()
        task._task_id = "test-id"
        task._dispatched_at = None

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        assert call_arg["metadata"]["dispatched_at"] is None

    def test_serialize_function_task_includes_func_metadata(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.serialize.return_value = b"serialized"
        service = TaskService(serializer=mock_serializer)

        async def my_func() -> str:
            return "result"

        task = FunctionTask(my_func)
        task._task_id = "test-id"

        # Act
        service.serialize_task(task)

        # Assert
        call_arg = mock_serializer.serialize.call_args[0][0]
        metadata = call_arg["metadata"]
        assert metadata["func_name"] == "my_func"
        assert "func_module" in metadata


@mark.unit
class TestTaskServiceDeserializeTask:
    """Test TaskService.deserialize_task() method."""

    @mark.asyncio
    async def test_deserialize_task_reconstructs_instance(self) -> None:
        # Arrange
        service = TaskService(serializer=MsgpackSerializer())
        task = ConcreteTask(public_param="test_value")
        task._task_id = "deserialize-test-id"
        task._attempts = 1
        task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        task.max_retries = 5
        task.queue = "test_queue"

        serialized = service.serialize_task(task)

        # Act
        result = await service.deserialize_task(serialized)

        # Assert
        assert isinstance(result, ConcreteTask)
        assert result._task_id == "deserialize-test-id"
        assert result._attempts == 1
        assert result.max_retries == 5
        assert result.queue == "test_queue"
        assert result.public_param == "test_value"

    @mark.asyncio
    async def test_deserialize_task_raises_on_invalid_class(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.deserialize = AsyncMock(
            return_value={
                "class": "nonexistent.module.FakeTask",
                "params": {},
                "metadata": {},
            }
        )
        service = TaskService(serializer=mock_serializer)

        # Act & Assert
        with raises(ModuleNotFoundError):
            await service.deserialize_task(b"fake_data")

    @mark.asyncio
    async def test_deserialize_task_restores_metadata(self) -> None:
        # Arrange
        service = TaskService(serializer=MsgpackSerializer())
        task = ConcreteTask()
        task._task_id = "metadata-test"
        task._attempts = 3
        task._dispatched_at = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
        task.max_retries = 10
        task.retry_delay = 60
        task.timeout = 120
        task.queue = "priority"

        serialized = service.serialize_task(task)

        # Act
        result = await service.deserialize_task(serialized)

        # Assert
        assert result._task_id == "metadata-test"
        assert result._attempts == 3
        assert result._dispatched_at is not None
        assert result.max_retries == 10
        assert result.retry_delay == 60
        assert result.timeout == 120
        assert result.queue == "priority"


@mark.unit
class TestTaskServiceExecuteTask:
    """Test TaskService.execute_task() method."""

    @mark.asyncio
    async def test_execute_task_calls_handle(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task.handle = AsyncMock(return_value="success")

        # Act
        await service.execute_task(task)

        # Assert
        task.handle.assert_awaited_once()

    @mark.asyncio
    async def test_execute_task_with_timeout(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task.timeout = 10
        task.handle = AsyncMock(return_value="success")

        # Act
        await service.execute_task(task)

        # Assert
        task.handle.assert_awaited_once()

    @mark.asyncio
    async def test_execute_task_raises_on_timeout(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task.timeout = 1  # Very short timeout

        async def slow_handle() -> str:
            import asyncio

            await asyncio.sleep(1.2)  # Sleep longer than timeout
            return "never"

        task.handle = slow_handle  # type: ignore[method-assign]

        # Act & Assert
        with raises(TimeoutError):
            await service.execute_task(task)


@mark.unit
class TestTaskServiceRetryLogic:
    """Test TaskService retry-related methods."""

    def test_should_retry_returns_true_when_retries_available(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._attempts = 0
        task.max_retries = 3
        exception = ValueError("test error")

        # Act
        result = service.should_retry(task, exception)

        # Assert
        assert result is True

    def test_should_retry_returns_false_when_max_retries_reached(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._attempts = 3
        task.max_retries = 3
        exception = ValueError("test error")

        # Act
        result = service.should_retry(task, exception)

        # Assert
        assert result is False

    def test_should_retry_respects_task_should_retry(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._attempts = 0
        task.max_retries = 3
        task.should_retry = MagicMock(return_value=False)
        exception = ValueError("test error")

        # Act
        result = service.should_retry(task, exception)

        # Assert
        assert result is False
        task.should_retry.assert_called_once_with(exception)

    def test_prepare_for_retry_increments_attempts(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._task_id = "retry-test"
        task._attempts = 1

        # Act
        service.prepare_for_retry(task)

        # Assert
        assert task._attempts == 2

    def test_prepare_for_retry_returns_serialized_bytes(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._task_id = "retry-test"
        task._attempts = 0

        # Act
        result = service.prepare_for_retry(task)

        # Assert
        assert isinstance(result, bytes)
        assert len(result) > 0


@mark.unit
class TestTaskServiceHandleTaskFailed:
    """Test TaskService.handle_task_failed() method."""

    @mark.asyncio
    async def test_handle_task_failed_calls_task_failed(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task.failed = AsyncMock()
        exception = ValueError("test error")

        # Act
        await service.handle_task_failed(task, exception)

        # Assert
        task.failed.assert_awaited_once_with(exception)

    @mark.asyncio
    async def test_handle_task_failed_catches_handler_exceptions(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task.failed = AsyncMock(side_effect=RuntimeError("Handler error"))
        exception = ValueError("original error")

        # Act - should not raise
        await service.handle_task_failed(task, exception)

        # Assert
        task.failed.assert_awaited_once()


@mark.unit
class TestTaskServiceDeserializeToTaskInfo:
    """Test TaskService.deserialize_to_task_info() method."""

    @mark.asyncio
    async def test_deserialize_to_task_info_with_nested_format(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._task_id = "info-test-id"
        task._attempts = 2
        task._dispatched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        task.queue = "test_queue"

        serialized = service.serialize_task(task)

        # Act
        result = await service.deserialize_to_task_info(serialized, "test_queue", "pending")

        # Assert
        assert isinstance(result, TaskInfo)
        assert result.id == "info-test-id"
        assert result.name == "ConcreteTask"
        assert result.queue == "test_queue"
        assert result.status == "pending"

    @mark.asyncio
    async def test_deserialize_to_task_info_handles_deserialization_error(self) -> None:
        # Arrange
        mock_serializer = MagicMock(spec=BaseSerializer)
        mock_serializer.deserialize = AsyncMock(side_effect=ValueError("Bad data"))
        service = TaskService(serializer=mock_serializer)

        # Act
        result = await service.deserialize_to_task_info(b"bad_data", "queue", "pending")

        # Assert
        assert isinstance(result, TaskInfo)
        assert result.id == "unknown"
        assert result.name == "unknown"


@mark.unit
class TestTaskServiceQueryOperations:
    """Test TaskService query operations (require driver)."""

    def test_require_driver_raises_without_driver(self) -> None:
        # Arrange
        service = TaskService()

        # Act & Assert
        with raises(ValueError, match="Driver required"):
            service._require_driver()

    def test_require_driver_returns_driver_when_set(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        service = TaskService(driver=mock_driver)

        # Act
        result = service._require_driver()

        # Assert
        assert result == mock_driver

    @mark.asyncio
    async def test_get_running_tasks_delegates_to_driver(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_running_tasks = AsyncMock(return_value=[(b"task1", "queue1")])
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.get_running_tasks(limit=10, offset=0)

        # Assert
        assert result == [(b"task1", "queue1")]
        mock_driver.get_running_tasks.assert_awaited_once_with(limit=10, offset=0)

    @mark.asyncio
    async def test_get_tasks_delegates_to_driver(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_tasks = AsyncMock(return_value=([(b"task1", "queue1", "pending")], 1))
        service = TaskService(driver=mock_driver)

        # Act
        result, total = await service.get_tasks(status="pending", queue="queue1")

        # Assert
        assert result == [(b"task1", "queue1", "pending")]
        assert total == 1

    @mark.asyncio
    async def test_retry_task_tries_driver_first(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.retry_task = AsyncMock(return_value=True)
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.retry_task("task-id")

        # Assert
        assert result is True
        mock_driver.retry_task.assert_awaited_once_with("task-id")

    @mark.asyncio
    async def test_retry_task_falls_back_to_raw_retry(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.retry_task = AsyncMock(return_value=False)
        mock_driver.get_task_by_id = AsyncMock(return_value=None)
        mock_driver.get_tasks = AsyncMock(return_value=([], 0))
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.retry_task("task-id")

        # Assert - no task found, returns False
        assert result is False

    @mark.asyncio
    async def test_delete_task_tries_driver_first(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.delete_task = AsyncMock(return_value=True)
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.delete_task("task-id")

        # Assert
        assert result is True
        mock_driver.delete_task.assert_awaited_once_with("task-id")

    @mark.asyncio
    async def test_delete_task_falls_back_to_raw_delete(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.delete_task = AsyncMock(return_value=False)
        mock_driver.get_task_by_id = AsyncMock(return_value=None)
        mock_driver.get_tasks = AsyncMock(return_value=([], 0))
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.delete_task("task-id")

        # Assert - no task found, returns False
        assert result is False


@mark.unit
class TestTaskServiceGetTaskById:
    """Test TaskService.get_task_by_id() method."""

    @mark.asyncio
    async def test_get_task_by_id_uses_driver_direct_lookup(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_task_by_id = AsyncMock(return_value=b"task_data")
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.get_task_by_id("task-id")

        # Assert
        assert result == (b"task_data", "unknown", "unknown")
        mock_driver.get_task_by_id.assert_awaited_once_with("task-id")

    @mark.asyncio
    async def test_get_task_by_id_falls_back_to_scanning(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()
        task._task_id = "scan-task-id"
        serialized = service.serialize_task(task)

        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_task_by_id = AsyncMock(return_value=None)
        mock_driver.get_tasks = AsyncMock(return_value=([(serialized, "queue1", "pending")], 1))
        service.driver = mock_driver

        # Act
        result = await service.get_task_by_id("scan-task-id")

        # Assert
        assert result is not None
        assert result[0] == serialized
        assert result[1] == "queue1"
        assert result[2] == "pending"

    @mark.asyncio
    async def test_get_task_by_id_returns_none_when_not_found(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_task_by_id = AsyncMock(return_value=None)
        mock_driver.get_tasks = AsyncMock(return_value=([], 0))
        service = TaskService(driver=mock_driver)

        # Act
        result = await service.get_task_by_id("nonexistent-id")

        # Assert
        assert result is None


@mark.unit
class TestTaskServiceUtilityMethods:
    """Test TaskService utility methods."""

    def test_parse_datetime_with_datetime_object(self) -> None:
        # Arrange
        service = TaskService()
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Act
        result = service._parse_datetime(dt)

        # Assert
        assert result == dt

    def test_parse_datetime_with_iso_string(self) -> None:
        # Arrange
        service = TaskService()

        # Act
        result = service._parse_datetime("2024-01-01T12:00:00+00:00")

        # Assert
        assert result is not None
        assert result.year == 2024

    def test_parse_datetime_with_timestamp(self) -> None:
        # Arrange
        service = TaskService()
        timestamp = 1704110400.0  # 2024-01-01 12:00:00 UTC

        # Act
        result = service._parse_datetime(timestamp)

        # Assert
        assert result is not None

    def test_parse_datetime_with_none(self) -> None:
        # Arrange
        service = TaskService()

        # Act
        result = service._parse_datetime(None)

        # Assert
        assert result is None

    def test_parse_datetime_with_invalid_string(self) -> None:
        # Arrange
        service = TaskService()

        # Act
        result = service._parse_datetime("not-a-date")

        # Assert
        assert result is None

    def test_is_function_task_returns_true_for_function_task(self) -> None:
        # Arrange
        service = TaskService()

        async def my_func() -> str:
            return "result"

        task = FunctionTask(my_func)

        # Act
        result = service._is_function_task(task)

        # Assert
        assert result is True

    def test_is_function_task_returns_false_for_class_task(self) -> None:
        # Arrange
        service = TaskService()
        task = ConcreteTask()

        # Act
        result = service._is_function_task(task)

        # Assert
        assert result is False


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
