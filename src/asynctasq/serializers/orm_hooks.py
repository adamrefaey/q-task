"""ORM model hooks for serialization/deserialization.

This module provides async hooks for ORM model serialization,
integrating with the hook system for SQLAlchemy, Django, and Tortoise ORM.
"""

import asyncio
import contextvars
from typing import TYPE_CHECKING, Any

from .hooks import AsyncTypeHook

if TYPE_CHECKING:
    pass

# =============================================================================
# ORM Availability Detection
# =============================================================================

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


# =============================================================================
# Base ORM Hook
# =============================================================================


class BaseOrmHook(AsyncTypeHook[Any]):
    """Base class for ORM-specific hooks.

    Provides common functionality for detecting and serializing ORM models.
    Subclasses implement ORM-specific detection, PK extraction, and fetching.
    """

    # Subclasses must define these
    orm_name: str = ""
    _type_key: str = ""  # Will be set dynamically

    @property
    def type_key(self) -> str:  # type: ignore[override]
        """Generate type key from ORM name."""
        return f"__orm:{self.orm_name}__"

    def _get_model_class_path(self, obj: Any) -> str:
        """Get the full class path for the model."""
        return f"{obj.__class__.__module__}.{obj.__class__.__name__}"

    def _import_model_class(self, class_path: str) -> type:
        """Import and return model class from class path."""
        module_name, class_name = class_path.rsplit(".", 1)
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name)

    def can_decode(self, data: dict[str, Any]) -> bool:
        """Check if this is an ORM reference we can decode."""
        return self.type_key in data and "__orm_class__" in data

    def encode(self, obj: Any) -> dict[str, Any]:
        """Encode ORM model to reference dictionary."""
        pk = self._get_model_pk(obj)
        class_path = self._get_model_class_path(obj)
        return {
            self.type_key: pk,
            "__orm_class__": class_path,
        }

    def _get_model_pk(self, obj: Any) -> Any:
        """Extract primary key from model. Override in subclasses."""
        raise NotImplementedError

    async def _fetch_model(self, model_class: type, pk: Any) -> Any:
        """Fetch model from database. Override in subclasses."""
        raise NotImplementedError

    async def decode_async(self, data: dict[str, Any]) -> Any:
        """Fetch ORM model from database using reference."""
        pk = data.get(self.type_key)
        class_path = data.get("__orm_class__")

        if pk is None or class_path is None:
            raise ValueError(f"Invalid ORM reference: {data}")

        model_class = self._import_model_class(class_path)
        return await self._fetch_model(model_class, pk)


# =============================================================================
# SQLAlchemy Hook
# =============================================================================


class SqlalchemyOrmHook(BaseOrmHook):
    """Hook for SQLAlchemy model serialization.

    Supports both async and sync SQLAlchemy sessions.
    Session must be provided via context variable on the model class.

    Example:
        >>> from contextvars import ContextVar
        >>> session_var: ContextVar[AsyncSession] = ContextVar("session")
        >>> MyModel._asynctasq_session_var = session_var
        >>>
        >>> async with async_session() as session:
        ...     session_var.set(session)
        ...     result = await pipeline.decode_async(data)
    """

    orm_name = "sqlalchemy"
    priority = 100  # High priority for ORM detection

    def can_encode(self, obj: Any) -> bool:
        """Check if object is a SQLAlchemy model."""
        if not SQLALCHEMY_AVAILABLE:
            return False
        try:
            from sqlalchemy import inspect as sqlalchemy_inspect

            return (
                hasattr(obj, "__mapper__")
                or (DeclarativeBase is not None and isinstance(obj, DeclarativeBase))
                or sqlalchemy_inspect(obj, raiseerr=False) is not None
            )
        except Exception:
            return False

    def _get_model_pk(self, obj: Any) -> Any:
        """Extract primary key from SQLAlchemy model."""
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

    async def _fetch_model(self, model_class: type, pk: Any) -> Any:
        """Fetch SQLAlchemy model from database."""
        if not SQLALCHEMY_AVAILABLE:
            raise ImportError("SQLAlchemy is not installed")

        # Try to get session from context variable on model class
        session_var: contextvars.ContextVar[Any] | None = getattr(
            model_class, "_asynctasq_session_var", None
        )

        if session_var is not None:
            session = session_var.get(None)
            if session is not None:
                # Try async session first
                try:
                    from sqlalchemy.ext.asyncio import AsyncSession

                    if isinstance(session, AsyncSession):
                        return await session.get(model_class, pk)
                except ImportError:
                    pass

                # Try sync session
                try:
                    from sqlalchemy.orm import Session

                    if isinstance(session, Session):
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None, lambda: session.get(model_class, pk)
                        )
                except ImportError:
                    pass

        raise RuntimeError(
            "SQLAlchemy session not available. Set _asynctasq_session_var on your model class."
        )


# =============================================================================
# Django Hook
# =============================================================================


class DjangoOrmHook(BaseOrmHook):
    """Hook for Django model serialization.

    Automatically uses Django's async ORM methods when available (Django 3.1+).
    Falls back to sync-in-executor for older versions.
    """

    orm_name = "django"
    priority = 100

    def can_encode(self, obj: Any) -> bool:
        """Check if object is a Django model."""
        if not DJANGO_AVAILABLE or django is None:
            return False
        try:
            return isinstance(obj, django.db.models.Model)
        except Exception:
            return False

    def _get_model_pk(self, obj: Any) -> Any:
        """Extract primary key from Django model."""
        return obj.pk

    async def _fetch_model(self, model_class: type, pk: Any) -> Any:
        """Fetch Django model from database."""
        if not DJANGO_AVAILABLE:
            raise ImportError("Django is not installed")

        # Try async method (Django 3.1+)
        try:
            return await model_class.objects.aget(pk=pk)
        except AttributeError:
            # Fallback to sync
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: model_class.objects.get(pk=pk))


# =============================================================================
# Tortoise ORM Hook
# =============================================================================


class TortoiseOrmHook(BaseOrmHook):
    """Hook for Tortoise ORM model serialization.

    Tortoise is async-native, so no special handling needed.
    """

    orm_name = "tortoise"
    priority = 100

    def can_encode(self, obj: Any) -> bool:
        """Check if object is a Tortoise model."""
        if not TORTOISE_AVAILABLE or TortoiseModel is None:
            return False
        try:
            return isinstance(obj, TortoiseModel)
        except Exception:
            return False

    def _get_model_pk(self, obj: Any) -> Any:
        """Extract primary key from Tortoise model."""
        return obj.pk

    async def _fetch_model(self, model_class: type, pk: Any) -> Any:
        """Fetch Tortoise model from database."""
        if not TORTOISE_AVAILABLE:
            raise ImportError("Tortoise ORM is not installed")

        return await model_class.get(pk=pk)


# =============================================================================
# Registry Helper
# =============================================================================


def register_orm_hooks(registry: Any) -> None:
    """Register all available ORM hooks with a registry.

    Only registers hooks for ORMs that are actually installed.

    Args:
        registry: HookRegistry to register hooks with
    """
    if SQLALCHEMY_AVAILABLE:
        registry.register(SqlalchemyOrmHook())

    if DJANGO_AVAILABLE:
        registry.register(DjangoOrmHook())

    if TORTOISE_AVAILABLE:
        registry.register(TortoiseOrmHook())
