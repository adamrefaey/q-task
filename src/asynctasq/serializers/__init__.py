"""Serialization implementations for asynctasq.

This module provides the serializer abstraction, concrete implementations
for encoding/decoding task data, and a pluggable hook system for custom types.

Hook System:
    The hook system allows registering custom type handlers for serialization.
    See :mod:`asynctasq.serializers.hooks` for details.

Example:
    >>> from asynctasq.serializers import MsgpackSerializer
    >>> from asynctasq.serializers.hooks import TypeHook
    >>>
    >>> class MyTypeHook(TypeHook[MyType]):
    ...     type_key = "__mytype__"
    ...     def can_encode(self, obj): return isinstance(obj, MyType)
    ...     def encode(self, obj): return {self.type_key: obj.to_dict()}
    ...     def decode(self, data): return MyType.from_dict(data[self.type_key])
    >>>
    >>> serializer = MsgpackSerializer()
    >>> serializer.register_hook(MyTypeHook())
"""

from .base_serializer import BaseSerializer
from .hooks import (
    AsyncTypeHook,
    HookRegistry,
    SerializationPipeline,
    TypeHook,
    create_default_registry,
)
from .msgpack_serializer import MsgpackSerializer
from .orm_hooks import (
    DjangoOrmHook,
    SqlalchemyOrmHook,
    TortoiseOrmHook,
    register_orm_hooks,
)
from .type_hooks import (
    DateHook,
    DatetimeHook,
    DecimalHook,
    SetHook,
    UUIDHook,
)

__all__ = [
    # Core
    "BaseSerializer",
    "MsgpackSerializer",
    # Hook System
    "TypeHook",
    "AsyncTypeHook",
    "HookRegistry",
    "SerializationPipeline",
    "create_default_registry",
    # Built-in Type Hooks
    "DatetimeHook",
    "DateHook",
    "DecimalHook",
    "UUIDHook",
    "SetHook",
    # ORM Hooks
    "SqlalchemyOrmHook",
    "DjangoOrmHook",
    "TortoiseOrmHook",
    "register_orm_hooks",
]
