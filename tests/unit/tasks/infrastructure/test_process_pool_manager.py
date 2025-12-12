"""Tests for ProcessPoolManager."""

from __future__ import annotations

import pytest

from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager


@pytest.fixture
def manager() -> ProcessPoolManager:
    """Create a ProcessPoolManager instance for testing."""
    return ProcessPoolManager()


@pytest.mark.unit
class TestProcessPoolManagerHealthMonitoring:
    """Test ProcessPoolManager health monitoring methods."""

    def test_is_initialized_returns_false_initially(self, manager: ProcessPoolManager) -> None:
        """Test is_initialized returns False before initialization."""
        assert not manager.is_initialized()

    def test_is_initialized_returns_true_after_init(self, manager: ProcessPoolManager) -> None:
        """Test is_initialized returns True after initialization."""
        manager.get_sync_pool()  # Trigger auto-initialization
        assert manager.is_initialized()

    def test_is_initialized_returns_false_after_shutdown(self, manager: ProcessPoolManager) -> None:
        """Test is_initialized returns False after shutdown."""
        manager.get_sync_pool()  # Trigger auto-initialization
        assert manager.is_initialized()

        import asyncio

        asyncio.run(manager.shutdown(wait=True))
        assert not manager.is_initialized()

    def test_get_stats_not_initialized(self, manager: ProcessPoolManager) -> None:
        """Test get_stats returns proper status when not initialized."""
        stats = manager.get_stats()

        assert stats["sync"]["status"] == "not_initialized"
        assert stats["async"]["status"] == "not_initialized"

    def test_get_stats_initialized(self, manager: ProcessPoolManager) -> None:
        """Test get_stats returns pool info when initialized."""
        # Create manager with specific config for this test
        test_manager = ProcessPoolManager(sync_max_workers=4)
        test_manager.get_sync_pool()  # Trigger initialization

        stats = test_manager.get_stats()

        assert stats["sync"]["status"] == "initialized"
        assert stats["sync"]["pool_size"] == 4
        assert stats["sync"]["max_tasks_per_child"] == 100

    def test_get_stats_without_max_tasks_per_child(self, manager: ProcessPoolManager) -> None:
        """Test get_stats when max_tasks_per_child is explicitly set."""
        # Create manager with specific config for this test
        test_manager = ProcessPoolManager(sync_max_workers=2, sync_max_tasks_per_child=100)
        test_manager.get_sync_pool()  # Trigger initialization

        stats = test_manager.get_stats()

        assert stats["sync"]["status"] == "initialized"
        assert stats["sync"]["pool_size"] == 2
        assert stats["sync"]["max_tasks_per_child"] == 100

    def test_is_initialized_thread_safe(self, manager: ProcessPoolManager) -> None:
        """Test that is_initialized is thread-safe."""
        import concurrent.futures
        import threading

        results = []
        lock = threading.Lock()

        def check_initialized() -> None:
            result = manager.is_initialized()
            with lock:
                results.append(result)

        # Initialize pool in one thread, check in others
        manager.get_sync_pool()  # Trigger initialization

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(check_initialized) for _ in range(10)]
            concurrent.futures.wait(futures)

        # All checks should return True
        assert all(results)
        assert len(results) == 10

    def test_get_stats_thread_safe(self, manager: ProcessPoolManager) -> None:
        """Test that get_stats is thread-safe."""
        import concurrent.futures
        import threading

        results = []
        lock = threading.Lock()

        # Create manager with specific config for this test
        test_manager = ProcessPoolManager(sync_max_workers=3, sync_max_tasks_per_child=50)
        test_manager.get_sync_pool()  # Trigger initialization

        def get_stats_check() -> None:
            stats = test_manager.get_stats()
            with lock:
                results.append(stats)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_stats_check) for _ in range(10)]
            concurrent.futures.wait(futures)

        # All checks should return consistent stats
        assert len(results) == 10
        for stats in results:
            assert stats["sync"]["status"] == "initialized"
            assert stats["sync"]["pool_size"] == 3
            assert stats["sync"]["max_tasks_per_child"] == 50


@pytest.mark.unit
class TestProcessPoolManagerValidation:
    """Test ProcessPoolManager input validation (Issue #16)."""

    def test_initialize_with_invalid_type_raises_type_error(
        self, manager: ProcessPoolManager
    ) -> None:
        """Test that non-integer max_workers raises TypeError when pool is created."""
        test_manager = ProcessPoolManager(sync_max_workers="invalid")  # type: ignore
        with pytest.raises(TypeError):
            test_manager.get_sync_pool()  # Error occurs here

    def test_initialize_with_float_raises_type_error(self, manager: ProcessPoolManager) -> None:
        """Test that float max_workers raises TypeError when pool is created."""
        test_manager = ProcessPoolManager(sync_max_workers=3.5)  # type: ignore
        with pytest.raises(TypeError):
            test_manager.get_sync_pool()  # Error occurs here

    def test_initialize_with_zero_raises_value_error(self, manager: ProcessPoolManager) -> None:
        """Test that max_workers=0 raises ValueError when pool is created."""
        test_manager = ProcessPoolManager(sync_max_workers=0)
        with pytest.raises(ValueError):
            test_manager.get_sync_pool()  # Error occurs here

    def test_initialize_with_negative_raises_value_error(self, manager: ProcessPoolManager) -> None:
        """Test that negative max_workers raises ValueError when pool is created."""
        test_manager = ProcessPoolManager(sync_max_workers=-5)
        with pytest.raises(ValueError):
            test_manager.get_sync_pool()  # Error occurs here

    def test_initialize_with_max_allowed_value_succeeds(self, manager: ProcessPoolManager) -> None:
        """Test that max_workers=1000 (large value) succeeds."""
        test_manager = ProcessPoolManager(sync_max_workers=1000)
        test_manager.get_sync_pool()  # Trigger initialization
        assert test_manager.is_initialized()
        stats = test_manager.get_stats()
        assert stats["sync"]["pool_size"] == 1000

    def test_initialize_with_valid_value_succeeds(self, manager: ProcessPoolManager) -> None:
        """Test that valid max_workers succeeds."""
        test_manager = ProcessPoolManager(sync_max_workers=4)
        test_manager.get_sync_pool()  # Trigger initialization
        assert test_manager.is_initialized()
        stats = test_manager.get_stats()
        assert stats["sync"]["pool_size"] == 4

    def test_initialize_with_none_uses_default(self, manager: ProcessPoolManager) -> None:
        """Test that max_workers=None uses CPU count default."""
        test_manager = ProcessPoolManager(sync_max_workers=None)
        test_manager.get_sync_pool()  # Trigger initialization
        assert test_manager.is_initialized()
        stats = test_manager.get_stats()
        # Should default to CPU count or 4
        assert stats["sync"]["pool_size"] is not None
        assert stats["sync"]["pool_size"] >= 1

    def test_initialize_with_boundary_value_one(self, manager: ProcessPoolManager) -> None:
        """Test that max_workers=1 (minimum) succeeds."""
        test_manager = ProcessPoolManager(sync_max_workers=1)
        test_manager.get_sync_pool()  # Trigger initialization
        assert test_manager.is_initialized()
        stats = test_manager.get_stats()
        assert stats["sync"]["pool_size"] == 1

    def test_error_message_includes_helpful_context(self, manager: ProcessPoolManager) -> None:
        """Test that error messages from ProcessPoolExecutor are clear."""
        test_manager = ProcessPoolManager(sync_max_workers=0)
        with pytest.raises(ValueError) as exc_info:
            test_manager.get_sync_pool()  # Error from ProcessPoolExecutor

        error_msg = str(exc_info.value)
        # ProcessPoolExecutor validation error
        assert "max_workers" in error_msg.lower()


@pytest.mark.unit
class TestProcessPoolManagerAdvanced:
    """Test ProcessPoolManager advanced features."""

    @pytest.mark.asyncio
    async def test_context_manager_async(self) -> None:
        """Test ProcessPoolManager as async context manager."""
        # Arrange & Act
        async with ProcessPoolManager(sync_max_workers=2) as manager:
            # Assert - should be initialized
            assert manager.is_initialized()
            pool = manager.get_sync_pool()
            assert pool is not None

        # Assert - should be shutdown after exit
        assert not manager.is_initialized()

    @pytest.mark.asyncio
    async def test_initialize_warm_event_loop(self) -> None:
        """Test initialize() sets up warm event loops."""
        from unittest.mock import patch

        # Arrange
        manager = ProcessPoolManager(async_max_workers=2)

        with patch("asynctasq.tasks.infrastructure.process_pool_manager.init_warm_event_loop"):
            # Act
            await manager.initialize()

            # Assert - warm loop initializer passed to pool
            assert manager.is_initialized()

    @pytest.mark.asyncio
    async def test_get_sync_pool_auto_initializes(self) -> None:
        """Test get_sync_pool() auto-initializes if not initialized."""
        # Arrange
        manager = ProcessPoolManager(sync_max_workers=3)

        # Act
        pool = manager.get_sync_pool()

        # Assert
        assert pool is not None
        assert manager.is_initialized()

    @pytest.mark.asyncio
    async def test_get_async_pool_auto_initializes(self) -> None:
        """Test get_async_pool() auto-initializes if not initialized."""
        # Arrange
        manager = ProcessPoolManager(async_max_workers=3)

        # Act
        pool = manager.get_async_pool()

        # Assert
        assert pool is not None
        assert manager.is_initialized()

    @pytest.mark.asyncio
    async def test_shutdown_with_cancel_futures(self) -> None:
        """Test shutdown(cancel_futures=True) cancels pending futures."""
        # Arrange
        manager = ProcessPoolManager(sync_max_workers=2)
        manager.get_sync_pool()

        # Act
        await manager.shutdown(wait=False, cancel_futures=True)

        # Assert
        assert not manager.is_initialized()

    @pytest.mark.asyncio
    async def test_fallback_count_functions(self) -> None:
        """Test get_fallback_count() and increment_fallback_count()."""
        from asynctasq.tasks.infrastructure.process_pool_manager import (
            get_fallback_count,
            increment_fallback_count,
        )

        # Arrange - get initial count
        initial = get_fallback_count()

        # Act
        count1 = increment_fallback_count()
        count2 = increment_fallback_count()
        final = get_fallback_count()

        # Assert
        assert count1 == initial + 1
        assert count2 == initial + 2
        assert final == initial + 2

    @pytest.mark.asyncio
    async def test_get_warm_event_loop_returns_none_outside_process(self) -> None:
        """Test get_warm_event_loop() returns None outside process pool."""
        from asynctasq.tasks.infrastructure.process_pool_manager import get_warm_event_loop

        # Act
        loop = get_warm_event_loop()

        # Assert (should be None in main process, not in subprocess)
        assert loop is None

    @pytest.mark.asyncio
    async def test_get_default_manager_returns_singleton(self) -> None:
        """Test get_default_manager() returns same instance."""
        from asynctasq.tasks.infrastructure.process_pool_manager import get_default_manager

        # Act
        manager1 = get_default_manager()
        manager2 = get_default_manager()

        # Assert
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_set_default_manager_replaces_instance(self) -> None:
        """Test set_default_manager() replaces default instance."""
        from asynctasq.tasks.infrastructure.process_pool_manager import (
            get_default_manager,
            set_default_manager,
        )

        # Arrange
        original = get_default_manager()
        custom = ProcessPoolManager(sync_max_workers=8)

        # Act
        set_default_manager(custom)
        new_default = get_default_manager()

        # Assert
        assert new_default is custom
        assert new_default is not original

        # Cleanup - restore original
        set_default_manager(original)

    @pytest.mark.asyncio
    async def test_get_cpu_count_returns_positive_int(self) -> None:
        """Test _get_cpu_count() returns positive integer."""
        # Arrange
        manager = ProcessPoolManager()

        # Act
        cpu_count = manager._get_cpu_count()

        # Assert
        assert isinstance(cpu_count, int)
        assert cpu_count > 0

    @pytest.mark.asyncio
    async def test_manager_with_custom_mp_context(self) -> None:
        """Test ProcessPoolManager with custom multiprocessing context."""
        import multiprocessing as mp

        # Arrange
        ctx = mp.get_context("spawn")  # Force spawn method
        manager = ProcessPoolManager(sync_max_workers=2, mp_context=ctx)

        # Act
        pool = manager.get_sync_pool()

        # Assert
        assert pool is not None
        assert manager.is_initialized()

    @pytest.mark.asyncio
    async def test_async_pool_has_separate_config(self) -> None:
        """Test async pool has independent configuration from sync pool."""
        # Arrange
        manager = ProcessPoolManager(
            sync_max_workers=2,
            async_max_workers=4,
            sync_max_tasks_per_child=50,
            async_max_tasks_per_child=100,
        )

        # Act
        manager.get_sync_pool()
        manager.get_async_pool()

        # Assert
        stats = manager.get_stats()
        assert stats["sync"]["pool_size"] == 2
        assert stats["async"]["pool_size"] == 4
        assert stats["sync"]["max_tasks_per_child"] == 50
        assert stats["async"]["max_tasks_per_child"] == 100

    @pytest.mark.asyncio
    async def test_get_stats_with_both_pools_initialized(self) -> None:
        """Test get_stats() with both sync and async pools initialized."""
        # Arrange
        manager = ProcessPoolManager(sync_max_workers=3, async_max_workers=5)
        manager.get_sync_pool()
        manager.get_async_pool()

        # Act
        stats = manager.get_stats()

        # Assert
        assert stats["sync"]["status"] == "initialized"
        assert stats["sync"]["pool_size"] == 3
        assert stats["async"]["status"] == "initialized"
        assert stats["async"]["pool_size"] == 5
