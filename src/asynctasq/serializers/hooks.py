"""Hook system for serialization/deserialization pipeline.

This module provides a unified hook architecture that allows:
- Built-in type handlers (datetime, Decimal, UUID, set, ORM models)
- User-defined custom type handlers
- Pre-serialization and post-deserialization processing

Example:
    >>> from asynctasq.serializers.hooks import TypeHook, HookRegistry
    >>>
    >>> class MoneyHook(TypeHook[Money]):
    ...     type_key = "__money__"
    ...     target_type = Money
    ...
    ...     def can_encode(self, obj: Any) -> bool:
    ...         return isinstance(obj, Money)
    ...
    ...     def encode(self, obj: Money) -> dict[str, Any]:
    ...         return {"amount": str(obj.amount), "currency": obj.currency}
    ...
    ...     def decode(self, data: dict[str, Any]) -> Money:
    ...         return Money(Decimal(data["amount"]), data["currency"])
    >>>
    >>> registry = HookRegistry()
    >>> registry.register(MoneyHook())
"""

from abc import ABC, abstractmethod
import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    pass

T = TypeVar("T")


class TypeHook[T](ABC):
    """Base class for type-specific serialization hooks.

    Implement this to add custom type support to the serializer.
    Each hook handles encoding (pre-serialize) and decoding (post-deserialize)
    for a specific type or family of types.

    Attributes:
        type_key: Unique string identifier used in serialized form (e.g., "__datetime__")
        priority: Hook priority (higher = checked first). Default is 0.
    """

    type_key: str
    priority: int = 0

    @abstractmethod
    def can_encode(self, obj: Any) -> bool:
        """Check if this hook can handle encoding the given object.

        Args:
            obj: Object to check

        Returns:
            True if this hook should handle the object
        """
        ...

    @abstractmethod
    def encode(self, obj: T) -> dict[str, Any]:
        """Encode object to a serializable dictionary.

        The returned dict should contain self.type_key as a key
        with the encoded value.

        Args:
            obj: Object to encode

        Returns:
            Dictionary with type_key and encoded data
        """
        ...

    def can_decode(self, data: dict[str, Any]) -> bool:
        """Check if this hook can handle decoding the given data.

        Default implementation checks for presence of type_key.

        Args:
            data: Dictionary to check

        Returns:
            True if this hook should handle the data
        """
        return self.type_key in data

    @abstractmethod
    def decode(self, data: dict[str, Any]) -> T:
        """Decode dictionary back to the original object.

        Args:
            data: Dictionary containing encoded data

        Returns:
            Reconstructed object
        """
        ...


class AsyncTypeHook(TypeHook[T]):
    """Type hook with async post-processing support.

    Use this for types that require async operations during deserialization,
    such as ORM models that need database fetches.
    """

    @abstractmethod
    async def decode_async(self, data: dict[str, Any]) -> T:
        """Async decode dictionary back to the original object.

        Args:
            data: Dictionary containing encoded data

        Returns:
            Reconstructed object
        """
        ...

    def decode(self, data: dict[str, Any]) -> T:
        """Sync decode returns the data as-is for async processing later.

        Override if you need sync fallback behavior.
        """
        return data  # type: ignore[return-value]

    @property
    def requires_async(self) -> bool:
        """Indicate this hook requires async post-processing."""
        return True


# =============================================================================
# Hook Registry
# =============================================================================


class HookRegistry:
    """Registry for managing serialization hooks.

    The registry maintains ordered lists of hooks for encoding and decoding.
    Hooks are checked in priority order (highest first) when processing objects.

    Example:
        >>> registry = HookRegistry()
        >>> registry.register(DatetimeHook())
        >>> registry.register(MyCustomHook())
        >>>
        >>> # Find hook for an object
        >>> hook = registry.find_encoder(datetime.now())
        >>> encoded = hook.encode(datetime.now())
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._hooks: list[TypeHook[Any]] = []
        self._async_hooks: list[AsyncTypeHook[Any]] = []
        self._decoder_cache: dict[str, TypeHook[Any]] = {}

    def register(self, hook: TypeHook[Any]) -> None:
        """Register a type hook.

        Args:
            hook: Hook instance to register

        Raises:
            ValueError: If a hook with the same type_key is already registered
        """
        # Check for duplicate type_key
        if hook.type_key in self._decoder_cache:
            raise ValueError(
                f"Hook with type_key '{hook.type_key}' already registered. "
                f"Use unregister() first if you want to replace it."
            )

        # Add to appropriate list
        if isinstance(hook, AsyncTypeHook):
            self._async_hooks.append(hook)
            self._async_hooks.sort(key=lambda h: h.priority, reverse=True)
        else:
            self._hooks.append(hook)
            self._hooks.sort(key=lambda h: h.priority, reverse=True)

        # Cache for decoder lookup
        self._decoder_cache[hook.type_key] = hook

    def unregister(self, type_key: str) -> TypeHook[Any] | None:
        """Unregister a hook by its type_key.

        Args:
            type_key: The type_key of the hook to remove

        Returns:
            The removed hook, or None if not found
        """
        hook = self._decoder_cache.pop(type_key, None)
        if hook is None:
            return None

        if isinstance(hook, AsyncTypeHook):
            self._async_hooks.remove(hook)
        else:
            self._hooks.remove(hook)

        return hook

    def find_encoder(self, obj: Any) -> TypeHook[Any] | None:
        """Find a hook that can encode the given object.

        Checks async hooks first, then sync hooks, in priority order.

        Args:
            obj: Object to find encoder for

        Returns:
            Hook that can encode the object, or None
        """
        # Check async hooks first (usually higher priority like ORM)
        for hook in self._async_hooks:
            if hook.can_encode(obj):
                return hook

        # Then check sync hooks
        for hook in self._hooks:
            if hook.can_encode(obj):
                return hook

        return None

    def find_decoder(self, data: dict[str, Any]) -> TypeHook[Any] | None:
        """Find a hook that can decode the given data.

        Uses cached type_key lookup for efficiency.

        Args:
            data: Dictionary to find decoder for

        Returns:
            Hook that can decode the data, or None
        """
        for key in data:
            if key in self._decoder_cache:
                return self._decoder_cache[key]
        return None

    def get_async_hooks(self) -> list[AsyncTypeHook[Any]]:
        """Get all registered async hooks.

        Returns:
            List of async hooks (for post-deserialization processing)
        """
        return list(self._async_hooks)

    @property
    def all_hooks(self) -> list[TypeHook[Any]]:
        """Get all registered hooks in priority order."""
        all_hooks: list[TypeHook[Any]] = [*self._async_hooks, *self._hooks]
        all_hooks.sort(key=lambda h: h.priority, reverse=True)
        return all_hooks

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._hooks.clear()
        self._async_hooks.clear()
        self._decoder_cache.clear()


# =============================================================================
# Default Registry with Built-in Hooks
# =============================================================================


def create_default_registry() -> HookRegistry:
    """Create a registry with all built-in type hooks.

    Returns:
        HookRegistry with datetime, date, Decimal, UUID, and set hooks
    """
    from .type_hooks import DateHook, DatetimeHook, DecimalHook, SetHook, UUIDHook

    registry = HookRegistry()

    # Register built-in hooks
    registry.register(DatetimeHook())
    registry.register(DateHook())
    registry.register(DecimalHook())
    registry.register(UUIDHook())
    registry.register(SetHook())

    return registry


# =============================================================================
# Pipeline Processor
# =============================================================================


class SerializationPipeline:
    """Unified pipeline for serialization/deserialization with hooks.

    This class orchestrates the hook system, providing:
    - Pre-serialization encoding via hooks
    - Post-deserialization async processing
    - Recursive structure traversal

    Example:
        >>> pipeline = SerializationPipeline()
        >>> pipeline.registry.register(MyCustomHook())
        >>>
        >>> # Encode for serialization
        >>> encoded = pipeline.encode({"timestamp": datetime.now()})
        >>>
        >>> # Decode after deserialization
        >>> decoded = await pipeline.decode_async(encoded)
    """

    def __init__(self, registry: HookRegistry | None = None) -> None:
        """Initialize pipeline with optional custom registry.

        Args:
            registry: Custom hook registry. If None, uses default with built-in hooks.
        """
        self.registry = registry or create_default_registry()

    def encode(self, obj: Any) -> Any:
        """Recursively encode an object using registered hooks.

        Traverses the object structure and applies matching hooks
        to convert custom types to serializable dictionaries.

        Args:
            obj: Object to encode (can be nested structure)

        Returns:
            Encoded object with custom types converted to dicts

        Raises:
            TypeError: If object contains types not handled by any hook
        """
        # Try to find an encoder hook
        hook = self.registry.find_encoder(obj)
        if hook is not None:
            return hook.encode(obj)

        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            processed = [self.encode(item) for item in obj]
            return processed if isinstance(obj, list) else tuple(processed)

        # Handle dictionaries
        if isinstance(obj, dict):
            return {key: self.encode(value) for key, value in obj.items()}

        # Return primitives as-is (will be handled by msgpack)
        return obj

    def decode(self, obj: Any) -> Any:
        """Synchronously decode custom types using registered hooks.

        This handles types that don't require async operations.
        Async types (like ORM models) are passed through for later processing.

        Args:
            obj: Object to decode

        Returns:
            Decoded object with sync types restored
        """
        if isinstance(obj, dict):
            # Try to find a decoder hook
            hook = self.registry.find_decoder(obj)
            if hook is not None:
                # If it's an async hook, pass through for later
                if isinstance(hook, AsyncTypeHook):
                    return obj
                return hook.decode(obj)

            # Recursively process dict values
            return {key: self.decode(value) for key, value in obj.items()}

        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            processed = [self.decode(item) for item in obj]
            return processed if isinstance(obj, list) else tuple(processed)

        return obj

    async def decode_async(self, obj: Any) -> Any:
        """Asynchronously decode all custom types including async hooks.

        This is the main deserialization entry point that handles
        both sync and async hooks, including ORM model fetching.

        Args:
            obj: Object to decode

        Returns:
            Fully decoded object with all types restored
        """
        if isinstance(obj, dict):
            # Try to find a decoder hook
            hook = self.registry.find_decoder(obj)
            if hook is not None:
                if isinstance(hook, AsyncTypeHook):
                    return await hook.decode_async(obj)
                return hook.decode(obj)

            # Recursively process dict values in parallel
            items = list(obj.items())
            keys = [key for key, _ in items]
            values = await asyncio.gather(*[self.decode_async(value) for _, value in items])
            return dict(zip(keys, values, strict=False))

        # Handle lists and tuples in parallel
        if isinstance(obj, (list, tuple)):
            processed = await asyncio.gather(*[self.decode_async(item) for item in obj])
            return list(processed) if isinstance(obj, list) else tuple(processed)

        return obj
