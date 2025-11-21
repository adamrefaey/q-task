"""Serialization implementations for async-task.

This module provides the serializer abstraction and concrete implementations
for encoding/decoding task data.
"""

from .base_serializer import BaseSerializer
from .msgpack_serializer import MsgpackSerializer

__all__ = [
    "BaseSerializer",
    "MsgpackSerializer",
]
