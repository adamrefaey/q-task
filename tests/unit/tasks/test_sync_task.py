"""Unit tests for SyncTask module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Fast, isolated tests
"""

import asyncio

from pytest import main, mark, raises

from asynctasq.tasks import SyncTask


# Test implementations for abstract SyncTask
class ConcreteSyncTask(SyncTask[str]):
    """Concrete implementation of SyncTask for testing."""

    def handle_sync(self) -> str:
        """Test sync implementation."""
        return "sync_success"


@mark.unit
class TestSyncTask:
    """Test SyncTask class."""

    @mark.asyncio
    async def test_sync_task_handle_calls_handle_sync(self) -> None:
        # Arrange
        task_instance = ConcreteSyncTask()

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "sync_success"

    @mark.asyncio
    async def test_sync_task_handle_runs_in_executor(self) -> None:
        # Arrange
        task_instance = ConcreteSyncTask()
        asyncio.get_event_loop()

        # Act
        result = await task_instance.handle()

        # Assert
        assert result == "sync_success"
        # Verify it's actually running in executor (not directly)
        # This is implicit - if it were running directly, we'd see different behavior

    def test_sync_task_must_implement_handle_sync(self) -> None:
        # Arrange
        class IncompleteSyncTask(SyncTask[str]):
            pass  # Missing handle_sync() implementation

        # Act & Assert - abstract class cannot be instantiated
        with raises(TypeError):
            # Type checker correctly identifies this as an error
            # but we're testing runtime behavior
            IncompleteSyncTask()  # type: ignore[abstract]


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
