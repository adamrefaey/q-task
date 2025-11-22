from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from msgpack import packb, unpackb

from .base_serializer import BaseSerializer


class MsgpackSerializer(BaseSerializer):
    """Msgpack-based serializer for task data with smart model handling.

    Features:
    - ORM models serialized as lightweight references (class + PK)
    - Custom type encoding (datetime, Decimal, UUID, sets)
    - Native msgpack handling for bytes (use_bin_type=True)
    - Recursive processing of nested structures
    """

    def serialize(self, obj: dict[str, Any]) -> bytes:
        """Serialize task data dict to msgpack bytes."""
        return cast(bytes, packb(obj, default=self._encode_custom_types, use_bin_type=True))

    def deserialize(self, data: bytes) -> dict[str, Any]:
        """Deserialize msgpack bytes back to task data dict."""
        return cast(dict[str, Any], unpackb(data, object_hook=self._decode_custom_types, raw=False))

    def _encode_custom_types(self, obj: Any) -> Any:
        """Encode Python types that msgpack doesn't support natively."""
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        elif isinstance(obj, date):
            return {"__date__": obj.isoformat()}
        elif isinstance(obj, Decimal):
            return {"__decimal__": str(obj)}
        elif isinstance(obj, UUID):
            return {"__uuid__": str(obj)}
        elif isinstance(obj, set):
            return {"__set__": list(obj)}
        raise TypeError(f"Object of type {type(obj)} is not msgpack serializable")

    def _decode_custom_types(self, obj: Any) -> Any:
        """Decode custom Python types from msgpack."""
        if isinstance(obj, dict):
            if "__datetime__" in obj:
                return datetime.fromisoformat(obj["__datetime__"])
            elif "__date__" in obj:
                return date.fromisoformat(obj["__date__"])
            elif "__decimal__" in obj:
                return Decimal(obj["__decimal__"])
            elif "__uuid__" in obj:
                return UUID(obj["__uuid__"])
            elif "__set__" in obj:
                return set(obj["__set__"])
        return obj
