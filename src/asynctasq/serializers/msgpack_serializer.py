"""Msgpack serializer with hook-based type handling.

This module provides the main serializer implementation using msgpack
with a pluggable hook system for custom type support.
"""

from typing import Any, cast

from msgpack import packb, unpackb

from .base_serializer import BaseSerializer
from .hooks import HookRegistry, SerializationPipeline, TypeHook, create_default_registry
from .orm_hooks import register_orm_hooks


def create_full_registry() -> HookRegistry:
    """Create a registry with all built-in hooks including ORM support.

    Returns:
        HookRegistry with datetime, date, Decimal, UUID, set, and ORM hooks
    """
    registry = create_default_registry()
    register_orm_hooks(registry)
    return registry


class MsgpackSerializer(BaseSerializer):
    """Msgpack-based serializer with pluggable hook system.

    Features:
    - Pluggable hook system for custom type serialization
    - Built-in support for datetime, date, Decimal, UUID, set
    - ORM model support (SQLAlchemy, Django, Tortoise)
    - Recursive processing of nested structures
    - User-defined hook registration

    Example:
        >>> from asynctasq.serializers import MsgpackSerializer
        >>> from asynctasq.serializers.hooks import TypeHook
        >>>
        >>> class MoneyHook(TypeHook[Money]):
        ...     type_key = "__money__"
        ...
        ...     def can_encode(self, obj: Any) -> bool:
        ...         return isinstance(obj, Money)
        ...
        ...     def encode(self, obj: Money) -> dict[str, Any]:
        ...         return {self.type_key: {"amount": str(obj.amount), "currency": obj.currency}}
        ...
        ...     def decode(self, data: dict[str, Any]) -> Money:
        ...         d = data[self.type_key]
        ...         return Money(Decimal(d["amount"]), d["currency"])
        >>>
        >>> serializer = MsgpackSerializer()
        >>> serializer.register_hook(MoneyHook())
    """

    def __init__(self, registry: HookRegistry | None = None) -> None:
        """Initialize serializer with optional custom registry.

        Args:
            registry: Custom hook registry. If None, uses default with all built-in hooks.
        """
        self._registry = registry or create_full_registry()
        self._pipeline = SerializationPipeline(self._registry)

    @property
    def registry(self) -> HookRegistry:
        """Access the hook registry for registration/inspection."""
        return self._registry

    @property
    def pipeline(self) -> SerializationPipeline:
        """Access the serialization pipeline."""
        return self._pipeline

    def register_hook(self, hook: TypeHook[Any]) -> None:
        """Register a custom type hook.

        Convenience method for self.registry.register(hook).

        Args:
            hook: TypeHook instance to register

        Raises:
            ValueError: If hook with same type_key already exists
        """
        self._registry.register(hook)

    def unregister_hook(self, type_key: str) -> TypeHook[Any] | None:
        """Unregister a hook by its type_key.

        Args:
            type_key: The type_key of the hook to remove

        Returns:
            The removed hook, or None if not found
        """
        return self._registry.unregister(type_key)

    def serialize(self, obj: dict[str, Any]) -> bytes:
        """Serialize task data dict to msgpack bytes.

        Custom types are automatically detected and converted via hooks.

        Args:
            obj: Task data dictionary to serialize

        Returns:
            Msgpack-encoded bytes
        """
        return cast(
            bytes,
            packb(obj, default=self._encode_with_hooks, use_bin_type=True),
        )

    async def deserialize(self, data: bytes) -> dict[str, Any]:
        """Deserialize msgpack bytes back to task data dict.

        Automatically restores custom types including async ORM model fetching.

        Args:
            data: Msgpack-encoded bytes

        Returns:
            Task data dictionary with all types restored
        """
        # First pass: msgpack unpack with sync type decoding
        result = cast(
            dict[str, Any],
            unpackb(data, object_hook=self._decode_with_hooks, raw=False),
        )

        # Second pass: async processing for ORM models and other async hooks
        if "params" in result:
            result["params"] = await self._pipeline.decode_async(result["params"])

        return result

    def _encode_with_hooks(self, obj: Any) -> Any:
        """Msgpack default encoder using hook system.

        Called by msgpack for types it can't handle natively.

        Args:
            obj: Object to encode

        Returns:
            Encoded representation

        Raises:
            TypeError: If no hook can handle the object
        """
        # Try to find an encoder hook
        hook = self._registry.find_encoder(obj)
        if hook is not None:
            return hook.encode(obj)

        raise TypeError(f"Object of type {type(obj)} is not msgpack serializable")

    def _decode_with_hooks(self, obj: Any) -> Any:
        """Msgpack object_hook decoder using hook system.

        Called by msgpack for each dictionary during unpacking.

        Args:
            obj: Object to decode

        Returns:
            Decoded object (sync types restored, async types passed through)
        """
        if isinstance(obj, dict):
            # Try to find a decoder hook
            hook = self._registry.find_decoder(obj)
            if hook is not None:
                return hook.decode(obj)

        return obj
