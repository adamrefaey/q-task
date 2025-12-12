"""Unit tests for MonitoringService module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock drivers and serializers to avoid real connections
- Fast, isolated tests
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from pytest import main, mark

from asynctasq.core.models import QueueStats, TaskInfo, WorkerInfo
from asynctasq.core.monitoring import MonitoringService
from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.serializers.base_serializer import BaseSerializer
from asynctasq.serializers.msgpack_serializer import MsgpackSerializer


@mark.unit
class TestMonitoringServiceInitialization:
    """Test MonitoringService.__init__() method."""

    def test_init_with_driver_only(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)

        # Act
        service = MonitoringService(driver=mock_driver)

        # Assert
        assert service.driver == mock_driver
        assert service.serializer is None
        assert service._task_serializer is not None
        assert service._task_executor is not None
        assert service._task_repository is not None

    def test_init_with_driver_and_serializer(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)

        # Act
        service = MonitoringService(driver=mock_driver, serializer=mock_serializer)

        # Assert
        assert service.driver == mock_driver
        assert service.serializer == mock_serializer

    def test_init_creates_task_services(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_serializer = MagicMock(spec=BaseSerializer)

        # Act
        service = MonitoringService(driver=mock_driver, serializer=mock_serializer)

        # Assert
        assert service._task_serializer is not None
        assert service._task_executor is not None
        assert service._task_repository is not None


@mark.unit
class TestMonitoringServiceGetQueueStats:
    """Test MonitoringService.get_queue_stats() method."""

    @mark.asyncio
    async def test_get_queue_stats_returns_queue_stats_model(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_queue_stats = AsyncMock(
            return_value={
                "name": "test_queue",
                "depth": 10,
                "processing": 2,
                "completed_total": 100,
                "failed_total": 5,
                "avg_duration_ms": 150.5,
                "throughput_per_minute": 25.0,
            }
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_queue_stats("test_queue")

        # Assert
        assert isinstance(result, QueueStats)
        assert result.name == "test_queue"
        assert result.depth == 10
        assert result.processing == 2
        assert result.completed_total == 100
        assert result.failed_total == 5
        assert result.avg_duration_ms == 150.5
        assert result.throughput_per_minute == 25.0

    @mark.asyncio
    async def test_get_queue_stats_handles_missing_optional_fields(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_queue_stats = AsyncMock(
            return_value={
                "name": "minimal_queue",
                "depth": 5,
                "processing": 1,
            }
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_queue_stats("minimal_queue")

        # Assert
        assert isinstance(result, QueueStats)
        assert result.name == "minimal_queue"
        assert result.depth == 5
        assert result.processing == 1
        assert result.completed_total == 0
        assert result.failed_total == 0
        assert result.avg_duration_ms is None
        assert result.throughput_per_minute is None


@mark.unit
class TestMonitoringServiceGetAllQueueStats:
    """Test MonitoringService.get_all_queue_stats() method."""

    @mark.asyncio
    async def test_get_all_queue_stats_returns_list(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_all_queue_names = AsyncMock(return_value=["queue1", "queue2"])
        mock_driver.get_queue_stats = AsyncMock(
            side_effect=[
                {"name": "queue1", "depth": 10, "processing": 1},
                {"name": "queue2", "depth": 20, "processing": 2},
            ]
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_all_queue_stats()

        # Assert
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(qs, QueueStats) for qs in result)
        assert result[0].name == "queue1"
        assert result[1].name == "queue2"

    @mark.asyncio
    async def test_get_all_queue_stats_empty_when_no_queues(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_all_queue_names = AsyncMock(return_value=[])
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_all_queue_stats()

        # Assert
        assert result == []


@mark.unit
class TestMonitoringServiceGetGlobalStats:
    """Test MonitoringService.get_global_stats() method."""

    @mark.asyncio
    async def test_get_global_stats_delegates_to_driver(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        expected_stats = {
            "pending": 100,
            "running": 10,
            "completed": 1000,
            "failed": 50,
            "total": 1160,
        }
        mock_driver.get_global_stats = AsyncMock(return_value=expected_stats)
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_global_stats()

        # Assert
        assert result == expected_stats
        mock_driver.get_global_stats.assert_awaited_once()


@mark.unit
class TestMonitoringServiceGetWorkerStats:
    """Test MonitoringService.get_worker_stats() method."""

    @mark.asyncio
    async def test_get_worker_stats_returns_worker_info_models(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_worker_stats = AsyncMock(
            return_value=[
                {
                    "worker_id": "worker-1",
                    "status": "active",
                    "current_task_id": "task-123",
                    "tasks_processed": 50,
                    "uptime_seconds": 3600,
                    "last_heartbeat": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                    "load_percentage": 75.0,
                }
            ]
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_worker_stats()

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1
        worker = result[0]
        assert isinstance(worker, WorkerInfo)
        assert worker.worker_id == "worker-1"
        assert worker.status == "active"
        assert worker.current_task_id == "task-123"
        assert worker.tasks_processed == 50
        assert worker.uptime_seconds == 3600
        assert worker.load_percentage == 75.0

    @mark.asyncio
    async def test_get_worker_stats_handles_string_heartbeat(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_worker_stats = AsyncMock(
            return_value=[
                {
                    "worker_id": "worker-2",
                    "status": "idle",
                    "last_heartbeat": "2024-01-01T12:00:00+00:00",
                }
            ]
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_worker_stats()

        # Assert
        assert len(result) == 1
        assert result[0].last_heartbeat is not None

    @mark.asyncio
    async def test_get_worker_stats_handles_timestamp_heartbeat(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_worker_stats = AsyncMock(
            return_value=[
                {
                    "worker_id": "worker-3",
                    "status": "idle",
                    "last_heartbeat": 1704110400.0,  # Unix timestamp
                }
            ]
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_worker_stats()

        # Assert
        assert len(result) == 1
        assert result[0].last_heartbeat is not None

    @mark.asyncio
    async def test_get_worker_stats_handles_invalid_heartbeat(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_worker_stats = AsyncMock(
            return_value=[
                {
                    "worker_id": "worker-4",
                    "status": "idle",
                    "last_heartbeat": "invalid-date",
                }
            ]
        )
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_worker_stats()

        # Assert
        assert len(result) == 1
        assert result[0].last_heartbeat is None


@mark.unit
class TestMonitoringServiceTaskDelegation:
    """Test MonitoringService task-related methods delegate to TaskService."""

    @mark.asyncio
    async def test_get_running_tasks_delegates(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_running_tasks = AsyncMock(return_value=[(b"task", "queue")])
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_running_tasks(limit=10, offset=5)

        # Assert
        assert result == [(b"task", "queue")]
        mock_driver.get_running_tasks.assert_awaited_once_with(limit=10, offset=5)

    @mark.asyncio
    async def test_get_running_task_infos_returns_task_info_models(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        serializer = MsgpackSerializer()

        # Create a properly serialized task
        task_data = {
            "class": "asynctasq.core.task.Task",
            "params": {},
            "metadata": {
                "task_id": "running-task-id",
                "attempts": 1,
                "dispatched_at": "2024-01-01T12:00:00+00:00",
                "queue": "default",
            },
        }
        raw_bytes = serializer.serialize(task_data)

        mock_driver.get_running_tasks = AsyncMock(return_value=[(raw_bytes, "default")])
        service = MonitoringService(driver=mock_driver, serializer=serializer)

        # Act
        result = await service.get_running_task_infos()

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TaskInfo)

    @mark.asyncio
    async def test_get_tasks_delegates(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_tasks = AsyncMock(return_value=([(b"task", "queue", "pending")], 1))
        service = MonitoringService(driver=mock_driver)

        # Act
        result, total = await service.get_tasks(status="pending", queue="queue", limit=50)

        # Assert
        assert result == [(b"task", "queue", "pending")]
        assert total == 1

    @mark.asyncio
    async def test_get_task_by_id_delegates(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_task_by_id = AsyncMock(return_value=b"task_data")
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_task_by_id("task-id")

        # Assert
        assert result is not None
        assert result[0] == b"task_data"

    @mark.asyncio
    async def test_get_task_info_by_id_returns_task_info(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        serializer = MsgpackSerializer()

        # Create a properly serialized task
        task_data = {
            "class": "asynctasq.core.task.Task",
            "params": {},
            "metadata": {
                "task_id": "info-task-id",
                "attempts": 0,
                "dispatched_at": "2024-01-01T12:00:00+00:00",
                "queue": "default",
            },
        }
        raw_bytes = serializer.serialize(task_data)

        mock_driver.get_task_by_id = AsyncMock(return_value=raw_bytes)
        service = MonitoringService(driver=mock_driver, serializer=serializer)

        # Act
        result = await service.get_task_info_by_id("info-task-id")

        # Assert
        assert isinstance(result, TaskInfo)
        assert result.id == "info-task-id"

    @mark.asyncio
    async def test_retry_task_delegates(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.retry_task = AsyncMock(return_value=True)
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.retry_task("task-id")

        # Assert
        assert result is True
        mock_driver.retry_task.assert_awaited_once_with("task-id")

    @mark.asyncio
    async def test_delete_task_delegates(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.delete_task = AsyncMock(return_value=True)
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.delete_task("task-id")

        # Assert
        assert result is True
        mock_driver.delete_task.assert_awaited_once_with("task-id")


@mark.unit
class TestMonitoringServiceGetAllQueueNames:
    """Test MonitoringService.get_all_queue_names() method."""

    @mark.asyncio
    async def test_get_all_queue_names_delegates_to_driver(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_all_queue_names = AsyncMock(return_value=["queue1", "queue2", "queue3"])
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_all_queue_names()

        # Assert
        assert result == ["queue1", "queue2", "queue3"]
        mock_driver.get_all_queue_names.assert_awaited_once()

    @mark.asyncio
    async def test_get_all_queue_names_empty_list(self) -> None:
        # Arrange
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver.get_all_queue_names = AsyncMock(return_value=[])
        service = MonitoringService(driver=mock_driver)

        # Act
        result = await service.get_all_queue_names()

        # Assert
        assert result == []


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
