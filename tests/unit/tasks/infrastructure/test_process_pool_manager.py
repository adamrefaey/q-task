"""Tests for ProcessPoolManager."""

from __future__ import annotations

import pytest

from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager


@pytest.mark.unit
class TestProcessPoolManagerHealthMonitoring:
    """Test ProcessPoolManager health monitoring methods."""

    def teardown_method(self) -> None:
        """Cleanup after each test."""
        if ProcessPoolManager.is_initialized():
            ProcessPoolManager.shutdown_pools()

    def test_is_initialized_returns_false_initially(self) -> None:
        """Test is_initialized returns False before initialization."""
        assert not ProcessPoolManager.is_initialized()

    def test_is_initialized_returns_true_after_init(self) -> None:
        """Test is_initialized returns True after initialization."""
        ProcessPoolManager.initialize_sync_pool(max_workers=2)
        assert ProcessPoolManager.is_initialized()

    def test_is_initialized_returns_false_after_shutdown(self) -> None:
        """Test is_initialized returns False after shutdown."""
        ProcessPoolManager.initialize_sync_pool(max_workers=2)
        assert ProcessPoolManager.is_initialized()

        ProcessPoolManager.shutdown_pools()
        assert not ProcessPoolManager.is_initialized()

    def test_get_stats_not_initialized(self) -> None:
        """Test get_stats returns proper status when not initialized."""
        stats = ProcessPoolManager.get_stats()

        assert stats["sync"]["status"] == "not_initialized"
        assert stats["async"]["status"] == "not_initialized"

    def test_get_stats_initialized(self) -> None:
        """Test get_stats returns pool info when initialized."""
        ProcessPoolManager.initialize_sync_pool(max_workers=4, max_tasks_per_child=100)

        stats = ProcessPoolManager.get_stats()

        assert stats["sync"]["status"] == "initialized"
        assert stats["sync"]["pool_size"] == 4
        assert stats["sync"]["max_tasks_per_child"] == 100

    def test_get_stats_without_max_tasks_per_child(self) -> None:
        """Test get_stats when max_tasks_per_child is None."""
        ProcessPoolManager.initialize_sync_pool(max_workers=2, max_tasks_per_child=None)

        stats = ProcessPoolManager.get_stats()

        assert stats["sync"]["status"] == "initialized"
        assert stats["sync"]["pool_size"] == 2
        assert stats["sync"]["max_tasks_per_child"] is None

    def test_is_initialized_thread_safe(self) -> None:
        """Test that is_initialized is thread-safe."""
        import concurrent.futures
        import threading

        results = []
        lock = threading.Lock()

        def check_initialized() -> None:
            result = ProcessPoolManager.is_initialized()
            with lock:
                results.append(result)

        # Initialize pool in one thread, check in others
        ProcessPoolManager.initialize_sync_pool(max_workers=2)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(check_initialized) for _ in range(10)]
            concurrent.futures.wait(futures)

        # All checks should return True
        assert all(results)
        assert len(results) == 10

    def test_get_stats_thread_safe(self) -> None:
        """Test that get_stats is thread-safe."""
        import concurrent.futures
        import threading

        results = []
        lock = threading.Lock()

        def get_stats_check() -> None:
            stats = ProcessPoolManager.get_stats()
            with lock:
                results.append(stats)

        ProcessPoolManager.initialize_sync_pool(max_workers=3, max_tasks_per_child=50)

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

    def teardown_method(self) -> None:
        """Cleanup after each test."""
        if ProcessPoolManager.is_initialized():
            ProcessPoolManager.shutdown_pools()

    def test_initialize_with_invalid_type_raises_type_error(self) -> None:
        """Test that non-integer max_workers raises TypeError."""
        with pytest.raises(
            TypeError,
            match="max_workers must be int, got str",
        ):
            ProcessPoolManager.initialize_sync_pool(max_workers="4")  # type: ignore

    def test_initialize_with_float_raises_type_error(self) -> None:
        """Test that float max_workers raises TypeError."""
        with pytest.raises(
            TypeError,
            match="max_workers must be int, got float",
        ):
            ProcessPoolManager.initialize_sync_pool(max_workers=4.5)  # type: ignore

    def test_initialize_with_zero_raises_value_error(self) -> None:
        """Test that max_workers=0 raises ValueError."""
        with pytest.raises(
            ValueError,
            match="max_workers must be >= 1, got 0",
        ):
            ProcessPoolManager.initialize_sync_pool(max_workers=0)

    def test_initialize_with_negative_raises_value_error(self) -> None:
        """Test that negative max_workers raises ValueError."""
        with pytest.raises(
            ValueError,
            match="max_workers must be >= 1, got -5",
        ):
            ProcessPoolManager.initialize_sync_pool(max_workers=-5)

    def test_initialize_with_max_allowed_value_succeeds(self) -> None:
        """Test that max_workers=1000 (large value) succeeds."""
        ProcessPoolManager.initialize_sync_pool(max_workers=1000)
        assert ProcessPoolManager.is_initialized()
        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["pool_size"] == 1000

    def test_initialize_with_valid_value_succeeds(self) -> None:
        """Test that valid max_workers succeeds."""
        ProcessPoolManager.initialize_sync_pool(max_workers=4)
        assert ProcessPoolManager.is_initialized()
        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["pool_size"] == 4

    def test_initialize_with_none_uses_default(self) -> None:
        """Test that max_workers=None uses CPU count default."""
        ProcessPoolManager.initialize_sync_pool(max_workers=None)
        assert ProcessPoolManager.is_initialized()
        stats = ProcessPoolManager.get_stats()
        # Should default to CPU count or 4
        assert stats["sync"]["pool_size"] is not None
        assert stats["sync"]["pool_size"] >= 1

    def test_initialize_with_boundary_value_one(self) -> None:
        """Test that max_workers=1 (minimum) succeeds."""
        ProcessPoolManager.initialize_sync_pool(max_workers=1)
        assert ProcessPoolManager.is_initialized()
        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["pool_size"] == 1

    def test_error_message_includes_helpful_context(self) -> None:
        """Test that error messages are clear."""
        with pytest.raises(ValueError) as exc_info:
            ProcessPoolManager.initialize_sync_pool(max_workers=0)

        error_msg = str(exc_info.value)
        assert "must be >= 1" in error_msg
        assert "got 0" in error_msg
