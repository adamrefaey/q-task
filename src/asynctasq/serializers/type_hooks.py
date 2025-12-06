"""Built-in type hooks for common Python types.

This module provides hooks for serializing/deserializing common Python types
that msgpack doesn't handle natively: datetime, date, Decimal, UUID, and set.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from .hooks import TypeHook


class DatetimeHook(TypeHook[datetime]):
    """Hook for datetime serialization."""

    type_key = "__datetime__"
    priority = 10

    def can_encode(self, obj: Any) -> bool:
        return isinstance(obj, datetime)

    def encode(self, obj: datetime) -> dict[str, Any]:
        return {self.type_key: obj.isoformat()}

    def decode(self, data: dict[str, Any]) -> datetime:
        return datetime.fromisoformat(data[self.type_key])


class DateHook(TypeHook[date]):
    """Hook for date serialization."""

    type_key = "__date__"
    priority = 10

    def can_encode(self, obj: Any) -> bool:
        # datetime is subclass of date, so exclude it
        return isinstance(obj, date) and not isinstance(obj, datetime)

    def encode(self, obj: date) -> dict[str, Any]:
        return {self.type_key: obj.isoformat()}

    def decode(self, data: dict[str, Any]) -> date:
        return date.fromisoformat(data[self.type_key])


class DecimalHook(TypeHook[Decimal]):
    """Hook for Decimal serialization."""

    type_key = "__decimal__"
    priority = 10

    def can_encode(self, obj: Any) -> bool:
        return isinstance(obj, Decimal)

    def encode(self, obj: Decimal) -> dict[str, Any]:
        return {self.type_key: str(obj)}

    def decode(self, data: dict[str, Any]) -> Decimal:
        return Decimal(data[self.type_key])


class UUIDHook(TypeHook[UUID]):
    """Hook for UUID serialization."""

    type_key = "__uuid__"
    priority = 10

    def can_encode(self, obj: Any) -> bool:
        return isinstance(obj, UUID)

    def encode(self, obj: UUID) -> dict[str, Any]:
        return {self.type_key: str(obj)}

    def decode(self, data: dict[str, Any]) -> UUID:
        return UUID(data[self.type_key])


class SetHook(TypeHook[set[Any]]):
    """Hook for set serialization."""

    type_key = "__set__"
    priority = 10

    def can_encode(self, obj: Any) -> bool:
        return isinstance(obj, set)

    def encode(self, obj: set[Any]) -> dict[str, Any]:
        return {self.type_key: list(obj)}

    def decode(self, data: dict[str, Any]) -> set[Any]:
        return set(data[self.type_key])
