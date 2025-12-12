"""Function reference resolution for FunctionTask deserialization."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FunctionResolver:
    """Resolves function references from module paths for FunctionTask deserialization."""

    @staticmethod
    def get_function_reference(
        func_module_name: str, func_name: str, func_file: str | None = None
    ) -> Callable[..., Any]:
        """Get function reference from module (handles __main__ module).

        Args:
            func_module_name: Module name (e.g., "myapp.tasks")
            func_name: Function name (e.g., "process_data")
            func_file: Optional file path for __main__ resolution

        Returns:
            Function reference

        Raises:
            ImportError: If module/function cannot be loaded
            FileNotFoundError: If __main__ file doesn't exist
        """
        # Handle __main__ module (running from script)
        if func_module_name == "__main__":
            if not func_file:
                raise ImportError(
                    f"Cannot import function {func_name} from __main__ "
                    f"(missing func_file in metadata)"
                )

            main_file = Path(func_file)
            if not main_file.exists():
                raise FileNotFoundError(
                    f"Cannot import function {func_name} from __main__ ({main_file} does not exist)"
                )

            spec = importlib.util.spec_from_file_location("__main__", main_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Failed to load spec for {main_file}")

            func_module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(func_module)
            except Exception as e:
                logger.exception(f"Failed to execute __main__ module: {e}")
                raise
        else:
            func_module = __import__(func_module_name, fromlist=[func_name])

        return getattr(func_module, func_name)
