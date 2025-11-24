from abc import abstractmethod
from typing import Any, Protocol


class BaseSerializer(Protocol):
    """Protocol for serializers"""

    @abstractmethod
    def serialize(self, obj: dict[str, Any]) -> bytes:
        """Serialize task data dictionary to bytes"""
        ...

    @abstractmethod
    async def deserialize(self, data: bytes) -> dict[str, Any]:
        """Deserialize bytes to task data dictionary"""
        ...
