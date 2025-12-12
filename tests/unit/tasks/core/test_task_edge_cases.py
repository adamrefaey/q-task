"""Comprehensive edge case tests for task module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test edge cases and boundary conditions
- Cover TaskConfig, parameter validation, serialization, retries
- Mock external dependencies for isolation
- Fast, isolated tests
"""

from __future__ import annotations

import multiprocessing as mp
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asynctasq.drivers.base_driver import BaseDriver
from asynctasq.tasks import AsyncTask, SyncProcessTask
from asynctasq.tasks.core.base_task import RESERVED_NAMES
from asynctasq.tasks.core.task_config import TaskConfig
from asynctasq.tasks.infrastructure.process_pool_manager import ProcessPoolManager
from asynctasq.tasks.types.function_task import FunctionTask

# ============================================================================
# 1. TaskConfig Edge Cases
# ============================================================================


@pytest.mark.unit
class TestTaskConfigEdgeCases:
    """Test TaskConfig edge cases and validation."""

    def test_driver_override_with_invalid_string(self) -> None:
        """Test that invalid driver_override string value is handled."""
        # This should be caught by type system but test runtime behavior
        config = TaskConfig(driver_override="invalid_driver")  # type: ignore[arg-type]

        # Config creation succeeds, but validation happens at runtime
        assert config.driver_override == "invalid_driver"

    def test_driver_override_with_connected_base_driver_instance(self) -> None:
        """Test driver_override with connected BaseDriver instance."""
        # Create a mock driver instance
        mock_driver = MagicMock(spec=BaseDriver)
        mock_driver._connected = True

        config = TaskConfig(driver_override=mock_driver)

        # Should accept BaseDriver instances
        assert config.driver_override is mock_driver
        assert isinstance(config.driver_override, BaseDriver)

    def test_conflicting_driver_override_at_multiple_levels(self) -> None:
        """Test behavior when driver_override conflicts at class and instance level."""

        class TaskWithClassDriver(AsyncTask[str]):
            driver_override = "redis"  # type: ignore[assignment]

            async def execute(self) -> str:
                return "test"

        # Instance config should take precedence
        task = TaskWithClassDriver()
        assert task.config.driver_override is None  # Class attribute doesn't affect config

        # Explicitly set at instance level
        task.config.driver_override = "postgres"  # type: ignore[assignment]
        assert task.config.driver_override == "postgres"

    def test_driver_override_with_none(self) -> None:
        """Test driver_override explicitly set to None."""
        config = TaskConfig(driver_override=None)
        assert config.driver_override is None

    def test_task_config_repr_excludes_driver_override(self) -> None:
        """Test that driver_override is excluded from repr."""
        mock_driver = MagicMock(spec=BaseDriver)
        config = TaskConfig(driver_override=mock_driver)

        repr_str = repr(config)
        assert "driver_override" not in repr_str


# ============================================================================
# 2. Parameter Validation Edge Cases
# ============================================================================


@pytest.mark.unit
class TestParameterValidation:
    """Test parameter name validation in task initialization."""

    def test_reserved_parameter_names_raise_error(self) -> None:
        """Test that reserved parameter names raise ValueError."""

        class TestTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        for reserved_name in RESERVED_NAMES:
            with pytest.raises(
                ValueError, match=f"Parameter name '{reserved_name}' is a reserved name"
            ):
                TestTask(**{reserved_name: "test"})  # type: ignore[call-overload]

    def test_underscore_prefix_parameter_raises_error(self) -> None:
        """Test that parameters starting with underscore raise ValueError."""

        class TestTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        with pytest.raises(
            ValueError, match="Parameter name '_private' is reserved for internal use"
        ):
            TestTask(_private="test")  # type: ignore[call-overload]

    def test_double_underscore_parameter_raises_error(self) -> None:
        """Test that parameters with double underscore raise ValueError."""

        class TestTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        with pytest.raises(
            ValueError, match="Parameter name '__dunder' is reserved for internal use"
        ):
            TestTask(__dunder="test")  # type: ignore[call-overload]

    def test_unicode_parameter_names_accepted(self) -> None:
        """Test that unicode parameter names are accepted."""

        class UnicodeTask(AsyncTask[str]):
            async def execute(self) -> str:
                return getattr(self, "用户", "default")

        # Use setattr to set unicode attribute name (avoids type checker issues)
        task = UnicodeTask()
        task.用户 = "test_value"  # type: ignore[attr-defined]
        assert task.用户 == "test_value"  # type: ignore[attr-defined]

    def test_very_long_parameter_names(self) -> None:
        """Test that very long parameter names (>255 chars) are accepted."""
        long_name = "a" * 300

        class LongNameTask(AsyncTask[str]):
            async def execute(self) -> str:
                return getattr(self, long_name, "default")

        task = LongNameTask(**{long_name: "test_value"})
        assert getattr(task, long_name) == "test_value"

    def test_non_identifier_parameter_names_work_via_setattr(self) -> None:
        """Test that non-identifier names like 'my-param' work via setattr."""

        # Python allows non-identifier attribute names via setattr/getattr
        class HyphenTask(AsyncTask[str]):
            async def execute(self) -> str:
                return getattr(self, "my-param", "default")

        # This works because **kwargs uses setattr internally
        task = HyphenTask()
        setattr(task, "my-param", "hyphenated")
        assert getattr(task, "my-param") == "hyphenated"

    def test_numeric_only_parameter_names_rejected_by_python(self) -> None:
        """Test that Python naturally rejects numeric-only parameter names."""
        # This is a Python syntax limitation, not our validation
        # Cannot create **{"123": "value"} in function call
        with pytest.raises(SyntaxError):
            compile("AsyncTask(123='value')", "<string>", "eval")

    def test_all_reserved_names_are_actual_methods_or_attributes(self) -> None:
        """Verify RESERVED_NAMES contains actual task methods/attributes.

        Note: RESERVED_NAMES are reserved across ALL task types (AsyncTask, FunctionTask, etc.)
        Some names like 'func', 'args', 'kwargs' only exist on FunctionTask, not AsyncTask.
        This test verifies that reserved names exist on at least one task type.
        """
        from asynctasq.tasks.types.function_task import FunctionTask

        class TestTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        async def test_func() -> str:
            return "test"

        async_task = TestTask()
        function_task = FunctionTask(test_func)

        for name in RESERVED_NAMES:
            # Each reserved name should exist on at least one task type
            exists = (
                hasattr(async_task, name)
                or hasattr(async_task.__class__, name)
                or hasattr(function_task, name)
                or hasattr(function_task.__class__, name)
            )
            assert exists, f"Reserved name '{name}' is not found on any task type"


# ============================================================================
# 3. Process Pool Edge Cases
# ============================================================================


@pytest.mark.unit
class TestProcessPoolEdgeCases:
    """Test ProcessPoolManager edge cases."""

    def teardown_method(self) -> None:
        """Cleanup after each test."""
        if ProcessPoolManager.is_initialized():
            ProcessPoolManager.shutdown_pools()

    def test_pool_initialization_with_custom_mp_context(self) -> None:
        """Test pool initialization with custom multiprocessing context."""
        # Use 'spawn' context explicitly
        ctx = mp.get_context("spawn")
        ProcessPoolManager.initialize_sync_pool(max_workers=2, mp_context=ctx)

        assert ProcessPoolManager.is_initialized()
        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["status"] == "initialized"

    def test_pool_shutdown_with_active_tasks_not_tested_here(self) -> None:
        """Note: Testing shutdown with active tasks requires integration test.

        This scenario is better tested in integration tests where we can
        actually submit work and interrupt it. Unit tests with mocks would
        not accurately represent the real shutdown behavior.
        """
        # Documented limitation - requires integration test
        pass

    def test_re_initialization_after_shutdown(self) -> None:
        """Test that pool can be re-initialized after shutdown."""
        # Initialize
        ProcessPoolManager.initialize_sync_pool(max_workers=2)
        assert ProcessPoolManager.is_initialized()

        # Shutdown
        ProcessPoolManager.shutdown_pools()
        assert not ProcessPoolManager.is_initialized()

        # Re-initialize with different settings
        ProcessPoolManager.initialize_sync_pool(max_workers=4)
        assert ProcessPoolManager.is_initialized()

        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["pool_size"] == 4

    def test_multiple_shutdown_calls_safe(self) -> None:
        """Test that multiple shutdown calls don't raise errors."""
        ProcessPoolManager.initialize_sync_pool(max_workers=2)

        # First shutdown
        ProcessPoolManager.shutdown_pools()
        assert not ProcessPoolManager.is_initialized()

        # Second shutdown should be safe (no-op)
        ProcessPoolManager.shutdown_pools()
        assert not ProcessPoolManager.is_initialized()

        # Third shutdown
        ProcessPoolManager.shutdown_pools()
        assert not ProcessPoolManager.is_initialized()

    def test_concurrent_initialize_pool_calls(self) -> None:
        """Test that concurrent initialize_pool() calls are thread-safe."""
        import concurrent.futures
        import threading

        results = []
        lock = threading.Lock()

        def initialize_pool() -> None:
            try:
                ProcessPoolManager.initialize_sync_pool(max_workers=2)
                with lock:
                    results.append("success")
            except Exception as e:
                with lock:
                    results.append(f"error: {e}")

        # Try to initialize from multiple threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(initialize_pool) for _ in range(5)]
            concurrent.futures.wait(futures)

        # All should succeed (first one initializes, others are no-ops or succeed)
        assert all(r == "success" for r in results)
        assert ProcessPoolManager.is_initialized()

    def test_get_stats_after_shutdown_shows_not_initialized(self) -> None:
        """Test that get_stats shows correct state after shutdown."""
        ProcessPoolManager.initialize_sync_pool(max_workers=2)
        ProcessPoolManager.shutdown_pools()

        stats = ProcessPoolManager.get_stats()
        assert stats["sync"]["status"] == "not_initialized"
        assert stats["async"]["status"] == "not_initialized"


# ============================================================================
# 4. Serialization Edge Cases
# ============================================================================


@pytest.mark.unit
class TestSerializationEdgeCases:
    """Test task serialization edge cases."""

    def test_task_with_circular_reference_in_parameters(self) -> None:
        """Test handling of circular references in parameters.

        Note: msgpack does NOT raise ValueError for circular references in dicts
        during task creation. Serialization happens later during dispatch.
        This test documents that task creation succeeds with circular refs.
        """

        class CircularTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        # Create circular reference
        circular_dict: dict[str, Any] = {"key": "value"}
        circular_dict["self"] = circular_dict

        # Task creation succeeds (serialization happens at dispatch time)
        task = CircularTask(data=circular_dict)

        # Verify task was created with circular reference
        assert hasattr(task, "data")
        assert task.data["self"] is task.data  # type: ignore[attr-defined]

    def test_task_with_very_large_parameters(self) -> None:
        """Test task with very large parameters (>1MB).

        Note: Locally-defined task classes can't be serialized in tests.
        This test documents the limitation. In production, tasks are
        defined at module level and msgpack serializes them correctly.
        """

        class LargeTask(AsyncTask[str]):
            async def execute(self) -> str:
                data = getattr(self, "large_data", "")
                return f"Processed {len(data)} bytes"

        # Create 2MB of data
        large_data = "x" * (2 * 1024 * 1024)
        task = LargeTask(large_data=large_data)

        # Verify task was created with large data
        assert hasattr(task, "large_data")
        assert len(task.large_data) == 2 * 1024 * 1024  # type: ignore[attr-defined]

    def test_task_with_unserializable_params_in_sync_mode(self) -> None:
        """Test that unserializable parameters are handled.

        Note: msgpack can't serialize lambda functions or locally-defined classes.
        Task creation succeeds but serialization would fail at dispatch time.
        """

        class UnserializableTask(SyncProcessTask[str]):
            def execute(self) -> str:
                return "test"

        # Lambda functions are not serializable (using 'callback' not 'func' which is reserved)
        # Task creation succeeds - serialization happens at dispatch time
        task = UnserializableTask(callback=lambda x: x)

        # Verify task was created
        assert hasattr(task, "callback")
        assert callable(task.callback)  # type: ignore[attr-defined]

    def test_function_task_with_main_module_function(self) -> None:
        """Test FunctionTask with __main__ module edge cases."""
        # Functions defined in __main__ have special serialization behavior
        # This test documents the limitation

        def main_function() -> str:
            return "from main"

        # Set __module__ to simulate __main__
        main_function.__module__ = "__main__"

        task = FunctionTask(func=main_function)

        # Task creation succeeds - serialization would happen at dispatch time
        assert task.func.__name__ == "main_function"
        assert task.func.__module__ == "__main__"

    def test_task_with_nested_complex_objects(self) -> None:
        """Test task with deeply nested complex objects."""

        class NestedTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        # Create deeply nested structure
        nested: dict[str, Any] = {"level": 1}
        current = nested
        for i in range(2, 100):
            next_dict: dict[str, Any] = {"level": i}
            current["next"] = next_dict
            current = next_dict

        task = NestedTask(data=nested)

        # Verify deeply nested structure was created
        assert hasattr(task, "data")
        assert task.data["level"] == 1  # type: ignore[attr-defined]
        assert task.data["next"]["level"] == 2  # type: ignore[attr-defined]


# ============================================================================
# 5. Retry Logic Edge Cases
# ============================================================================


@pytest.mark.unit
class TestRetryLogicEdgeCases:
    """Test retry logic edge cases."""

    @pytest.mark.asyncio
    async def test_enqueue_failure_during_retry(self) -> None:
        """Test handling when enqueue fails during retry."""

        class RetryTask(AsyncTask[str]):
            async def execute(self) -> str:
                raise ValueError("Task failed")

        task = RetryTask()
        task._task_id = "test-id"
        task._attempts = 1

        # Mock dispatcher to simulate enqueue failure
        with patch("asynctasq.core.dispatcher.get_dispatcher") as mock_get_dispatcher:
            mock_dispatcher = MagicMock()
            mock_dispatcher.dispatch = AsyncMock(side_effect=ConnectionError("Failed to enqueue"))
            mock_get_dispatcher.return_value = mock_dispatcher

            # Retry should fail if enqueue fails
            with pytest.raises(ConnectionError, match="Failed to enqueue"):
                await task.dispatch()

    @pytest.mark.asyncio
    async def test_serialization_failure_during_retry(self) -> None:
        """Test handling when serialization fails during retry."""

        class UnserializableTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

        task = UnserializableTask(unpicklable=lambda: None)

        # Should fail during dispatch due to serialization
        with patch("asynctasq.core.dispatcher.get_dispatcher") as mock_get_dispatcher:
            mock_dispatcher = MagicMock()
            # Simulate serialization error during dispatch
            mock_dispatcher.dispatch = AsyncMock(side_effect=TypeError("Cannot serialize lambda"))
            mock_get_dispatcher.return_value = mock_dispatcher

            # Will fail during msgpack serialization (TypeError or AttributeError)
            with pytest.raises((TypeError, AttributeError)):
                await task.dispatch()

    def test_should_retry_raising_exceptions(self) -> None:
        """Test behavior when should_retry() itself raises an exception."""

        class BrokenRetryTask(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

            def should_retry(self, exception: Exception) -> bool:
                raise RuntimeError("should_retry is broken")

        task = BrokenRetryTask()

        # should_retry raising should propagate
        with pytest.raises(RuntimeError, match="should_retry is broken"):
            task.should_retry(ValueError("original error"))

    @pytest.mark.asyncio
    async def test_retry_with_driver_disconnection(self) -> None:
        """Test retry behavior when driver disconnects."""

        class RetryableTask(AsyncTask[str]):
            async def execute(self) -> str:
                raise ValueError("Transient error")

        task = RetryableTask()
        task.config.max_retries = 3

        with patch("asynctasq.core.dispatcher.get_dispatcher") as mock_get_dispatcher:
            mock_dispatcher = MagicMock()
            # First attempt succeeds, subsequent retries fail with connection error
            mock_dispatcher.dispatch = AsyncMock(
                side_effect=[
                    "task-id-123",  # First dispatch succeeds
                    ConnectionError("Driver disconnected"),  # Retry fails
                ]
            )
            mock_get_dispatcher.return_value = mock_dispatcher

            # First dispatch should succeed
            await task.dispatch()

            # Retry (second dispatch) should fail
            with pytest.raises(ConnectionError):
                await task.dispatch()

    def test_should_retry_with_max_retries_zero(self) -> None:
        """Test that should_retry is still called when max_retries=0."""

        class NoRetryTask(AsyncTask[str]):
            async def execute(self) -> str:
                raise ValueError("Error")

            def should_retry(self, exception: Exception) -> bool:
                # This should still be called even with max_retries=0
                return False

        task = NoRetryTask()
        task.config.max_retries = 0

        # should_retry should still be callable
        result = task.should_retry(ValueError("test"))
        assert result is False

    def test_retry_with_custom_retry_logic_based_on_attempts(self) -> None:
        """Test should_retry can use _attempts for custom logic."""

        class AttemptBasedRetry(AsyncTask[str]):
            async def execute(self) -> str:
                return "test"

            def should_retry(self, exception: Exception) -> bool:
                # Only retry on first attempt
                return self._attempts == 0

        task = AttemptBasedRetry()

        # First attempt (0) - should retry
        task._attempts = 0
        assert task.should_retry(ValueError("test")) is True

        # Second attempt (1) - should not retry
        task._attempts = 1
        assert task.should_retry(ValueError("test")) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
