from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from msgpack import packb, unpackb

from .base_serializer import BaseSerializer
from .orm_handler import OrmHandler


class MsgpackSerializer(BaseSerializer):
    """Msgpack-based serializer for task data with smart model handling.

    Features:
    - ORM models serialized as lightweight references (class + PK)
    - Custom type encoding (datetime, Decimal, UUID, sets)
    - Native msgpack handling for bytes (use_bin_type=True)
    - Recursive processing of nested structures
    """

    def __init__(self) -> None:
        """Initialize serializer with ORM handler."""
        self.orm_handler = OrmHandler()

    def serialize(self, obj: dict[str, Any]) -> bytes:
        """Serialize task data dict to msgpack bytes.

        ORM models are automatically detected and converted to references
        via the _encode_custom_types hook.
        """
        return cast(bytes, packb(obj, default=self._encode_custom_types, use_bin_type=True))

    async def deserialize(self, data: bytes) -> dict[str, Any]:
        """Deserialize msgpack bytes back to task data dict.

        Automatically fetches ORM models from database during deserialization.
        """
        # First, deserialize to get structure with ORM references
        result = cast(
            dict[str, Any], unpackb(data, object_hook=self._decode_custom_types, raw=False)
        )

        # Then process to fetch ORM models
        if "params" in result:
            result["params"] = await self.orm_handler.process_for_deserialization(result["params"])

        return result

    def _encode_custom_types(self, obj: Any) -> Any:
        """Encode Python types that msgpack doesn't support natively.

        Handles:
        - datetime, date, Decimal, UUID, set (built-in types)
        - ORM models (converted to lightweight references)
        """
        # Handle built-in custom types
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

        # Handle ORM models - convert to reference
        if self.orm_handler.is_orm_model(obj):
            return self.orm_handler.serialize_model(obj)

        raise TypeError(f"Object of type {type(obj)} is not msgpack serializable")

    def _decode_custom_types(self, obj: Any) -> Any:
        """Decode custom Python types from msgpack.

        Handles:
        - datetime, date, Decimal, UUID, set (built-in types)
        - ORM references (detected and passed through for async fetching in deserialize)
        """
        if isinstance(obj, dict):
            # Handle built-in custom types
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

            # Detect ORM references - pass through for async fetching in deserialize()
            if self.orm_handler._is_orm_reference(obj):
                return obj

        return obj
