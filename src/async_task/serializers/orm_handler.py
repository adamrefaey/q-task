"""ORM model handler for serialization/deserialization.

This module provides functionality to detect ORM models and convert them
to lightweight references during serialization, then fetch them back
from the database during deserialization.
"""

import asyncio
import contextvars
from typing import Any

# Try importing ORMs (optional dependencies)
try:
    from sqlalchemy.orm import DeclarativeBase

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    DeclarativeBase = None  # type: ignore[assignment, misc]

try:
    import django.db.models

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    django = None  # type: ignore[assignment]

try:
    from tortoise.models import Model as TortoiseModel

    TORTOISE_AVAILABLE = True
except ImportError:
    TORTOISE_AVAILABLE = False
    TortoiseModel = None  # type: ignore[assignment, misc]


class OrmHandler:
    """Handles ORM model serialization and deserialization.

    Detects ORM models from supported ORMs and converts them to lightweight
    references during serialization. During deserialization, fetches the
    models back from the database using async methods when available.

    Supported ORMs:
    - SQLAlchemy (async and sync)
    - Django ORM (async and sync)
    - Tortoise ORM (async)
    """

    @staticmethod
    def _is_sqlalchemy_model(obj: Any) -> bool:
        """Check if object is a SQLAlchemy model instance."""
        if not SQLALCHEMY_AVAILABLE:
            return False
        try:
            # Import here to ensure it's available when needed
            from sqlalchemy import inspect as sqlalchemy_inspect

            # Check if it's an instance of a mapped class
            return (
                hasattr(obj, "__mapper__")
                or (DeclarativeBase is not None and isinstance(obj, DeclarativeBase))
                or sqlalchemy_inspect(obj, raiseerr=False) is not None
            )
        except Exception:
            return False

    @staticmethod
    def _is_django_model(obj: Any) -> bool:
        """Check if object is a Django model instance."""
        if not DJANGO_AVAILABLE or django is None:
            return False
        try:
            return isinstance(obj, django.db.models.Model)
        except Exception:
            return False

    @staticmethod
    def _is_tortoise_model(obj: Any) -> bool:
        """Check if object is a Tortoise ORM model instance."""
        if not TORTOISE_AVAILABLE or TortoiseModel is None:
            return False
        try:
            return isinstance(obj, TortoiseModel)
        except Exception:
            return False

    def is_orm_model(self, obj: Any) -> bool:
        """Check if object is an ORM model from any supported ORM."""
        return (
            self._is_sqlalchemy_model(obj)
            or self._is_django_model(obj)
            or self._is_tortoise_model(obj)
        )

    def _get_orm_type(self, obj: Any) -> str | None:
        """Get the ORM type identifier for the model."""
        if self._is_sqlalchemy_model(obj):
            return "sqlalchemy"
        elif self._is_django_model(obj):
            return "django"
        elif self._is_tortoise_model(obj):
            return "tortoise"
        return None

    def _get_model_pk(self, obj: Any) -> Any:
        """Get the primary key value from an ORM model."""
        orm_type = self._get_orm_type(obj)
        if not orm_type:
            raise ValueError(f"Object is not a recognized ORM model: {type(obj)}")

        try:
            if orm_type == "sqlalchemy":
                # SQLAlchemy: use inspect to get primary key
                if not SQLALCHEMY_AVAILABLE:
                    raise ImportError("SQLAlchemy is not installed")
                from sqlalchemy import inspect as sqlalchemy_inspect

                mapper = sqlalchemy_inspect(obj.__class__)
                pk_columns = mapper.primary_key
                if len(pk_columns) == 1:
                    return getattr(obj, pk_columns[0].name)
                else:
                    # Composite primary key - return tuple
                    return tuple(getattr(obj, col.name) for col in pk_columns)
            elif orm_type == "django":
                # Django: use pk property
                return obj.pk
            elif orm_type == "tortoise":
                # Tortoise: use pk property
                return obj.pk
        except Exception as e:
            raise ValueError(f"Failed to get primary key from {orm_type} model: {e}") from e

    def _get_model_class_path(self, obj: Any) -> str:
        """Get the full class path for the model."""
        return f"{obj.__class__.__module__}.{obj.__class__.__name__}"

    def serialize_model(self, obj: Any) -> dict[str, Any]:
        """Convert an ORM model to a serializable reference.

        Args:
            obj: ORM model instance

        Returns:
            Dictionary with ORM reference: {"__orm:orm_type__": pk, "__orm_class__": "module.ClassName"}

        Raises:
            ValueError: If object is not a recognized ORM model
        """
        orm_type = self._get_orm_type(obj)
        if not orm_type:
            raise ValueError(f"Object is not a recognized ORM model: {type(obj)}")

        pk = self._get_model_pk(obj)
        class_path = self._get_model_class_path(obj)

        return {
            f"__orm:{orm_type}__": pk,
            "__orm_class__": class_path,
        }

    def process_for_serialization(self, obj: Any) -> Any:
        """Recursively process an object to replace ORM models with references.

        Handles:
        - ORM model instances
        - Lists/tuples containing models
        - Dictionaries with model values
        - Nested structures

        Args:
            obj: Object to process

        Returns:
            Processed object with models replaced by references
        """
        # Check if it's an ORM model
        if self.is_orm_model(obj):
            return self.serialize_model(obj)

        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            processed = [self.process_for_serialization(item) for item in obj]
            return processed if isinstance(obj, list) else tuple(processed)

        # Handle dictionaries
        if isinstance(obj, dict):
            return {key: self.process_for_serialization(value) for key, value in obj.items()}

        # Return as-is for other types
        return obj

    def _is_orm_reference(self, obj: Any) -> bool:
        """Check if object is an ORM reference dictionary."""
        if not isinstance(obj, dict):
            return False
        # Check for any ORM reference key
        return (
            any(key.startswith("__orm:") and key.endswith("__") for key in obj.keys())
            and "__orm_class__" in obj
        )

    def _get_orm_type_from_reference(self, ref: dict[str, Any]) -> str | None:
        """Extract ORM type from reference dictionary."""
        for key in ref.keys():
            if key.startswith("__orm:") and key.endswith("__"):
                return key[6:-2]  # Extract "sqlalchemy" from "__orm:sqlalchemy__"
        return None

    async def _fetch_sqlalchemy_model(self, model_class: type, pk: Any) -> Any:
        """Fetch SQLAlchemy model from database (async)."""
        if not SQLALCHEMY_AVAILABLE:
            raise ImportError("SQLAlchemy is not installed")

        # Try to get session from context or use default
        # Support both async and sync sessions
        session_var: contextvars.ContextVar[Any] | None = getattr(
            model_class, "_async_task_session_var", None
        )
        if session_var is not None:
            session = session_var.get()
            if session is not None:
                # Check if it's an async session
                try:
                    from sqlalchemy.ext.asyncio import AsyncSession

                    if isinstance(session, AsyncSession):
                        return await session.get(model_class, pk)
                except ImportError:
                    pass

                # Check if it's a sync session
                try:
                    from sqlalchemy.orm import Session

                    if isinstance(session, Session):
                        # Run sync operation in executor
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None, lambda: session.get(model_class, pk)
                        )
                except ImportError:
                    pass

        # No valid session found
        raise RuntimeError(
            "SQLAlchemy session not available. "
            "Set _async_task_session_var on your model class or pass session explicitly."
        )

    async def _fetch_django_model(self, model_class: type, pk: Any) -> Any:
        """Fetch Django model from database (async)."""
        if not DJANGO_AVAILABLE:
            raise ImportError("Django is not installed")

        # Django 3.1+ supports async queries
        try:
            return await model_class.objects.aget(pk=pk)
        except AttributeError:
            # Fallback to sync if async not available
            loop = asyncio.get_event_loop()

            def _fetch_sync():
                return model_class.objects.get(pk=pk)

            return await loop.run_in_executor(None, _fetch_sync)

    async def _fetch_tortoise_model(self, model_class: type, pk: Any) -> Any:
        """Fetch Tortoise ORM model from database (async)."""
        if not TORTOISE_AVAILABLE:
            raise ImportError("Tortoise ORM is not installed")

        return await model_class.get(pk=pk)

    async def deserialize_model(self, ref: dict[str, Any]) -> Any:
        """Fetch an ORM model from database using reference.

        Args:
            ref: ORM reference dictionary with keys:
                - "__orm:orm_type__": primary key value
                - "__orm_class__": full class path (module.ClassName)

        Returns:
            ORM model instance

        Raises:
            ImportError: If required ORM is not installed
            ValueError: If reference format is invalid
            RuntimeError: If model cannot be fetched (e.g., session not available)
        """
        if not self._is_orm_reference(ref):
            raise ValueError(f"Invalid ORM reference format: {ref}")

        orm_type = self._get_orm_type_from_reference(ref)
        if not orm_type:
            raise ValueError(f"Could not determine ORM type from reference: {ref}")

        # Get primary key
        orm_key = f"__orm:{orm_type}__"
        pk = ref.get(orm_key)
        if pk is None:
            raise ValueError(f"Primary key not found in reference: {ref}")

        # Get class path and import
        class_path = ref.get("__orm_class__")
        if not class_path:
            raise ValueError(f"Class path not found in reference: {ref}")

        # Import model class
        module_name, class_name = class_path.rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        model_class = getattr(module, class_name)

        # Fetch model based on ORM type
        if orm_type == "sqlalchemy":
            return await self._fetch_sqlalchemy_model(model_class, pk)
        elif orm_type == "django":
            return await self._fetch_django_model(model_class, pk)
        elif orm_type == "tortoise":
            return await self._fetch_tortoise_model(model_class, pk)
        else:
            raise ValueError(f"Unsupported ORM type: {orm_type}")

    async def process_for_deserialization(self, obj: Any) -> Any:
        """Recursively process an object to replace ORM references with models.

        Handles:
        - ORM reference dictionaries
        - Lists/tuples containing references
        - Dictionaries with reference values
        - Nested structures

        Args:
            obj: Object to process

        Returns:
            Processed object with references replaced by model instances
        """
        # Check if it's an ORM reference
        if self._is_orm_reference(obj):
            return await self.deserialize_model(obj)

        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            processed = await asyncio.gather(
                *[self.process_for_deserialization(item) for item in obj]
            )
            return processed if isinstance(obj, list) else tuple(processed)

        # Handle dictionaries
        if isinstance(obj, dict):
            # Process values in parallel where possible
            items = list(obj.items())
            keys = [key for key, _ in items]
            values = await asyncio.gather(
                *[self.process_for_deserialization(value) for _, value in items]
            )
            return dict(zip(keys, values, strict=False))

        # Return as-is for other types
        return obj
