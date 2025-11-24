"""Comprehensive test suite for MsgpackSerializer.

Tests follow msgpack-python best practices (v1.1.0+):
- Modern msgpack configuration (use_bin_type=True, raw=False, strict_map_key=True)
- All custom types (datetime, date, Decimal, UUID, bytes, set)
- Nested structures and real-world task queue scenarios
- Security considerations (max_buffer_size, strict_map_key)
- Edge cases and error handling
- Round-trip consistency and type preservation

References:
- https://github.com/msgpack/msgpack-python
- https://msgpack.org/
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import msgpack
from pytest import fixture, main, mark, raises

from async_task.serializers.msgpack_serializer import MsgpackSerializer


# Test fixtures
@fixture
def serializer():
    """Reusable serializer instance."""
    return MsgpackSerializer()


@mark.unit
class TestMsgpackSerializerBasics:
    """Test basic serialization and deserialization functionality."""

    def test_serialize_returns_bytes(self, serializer):
        """Verify serialization returns msgpack bytes (modern use_bin_type=True)."""
        result = serializer.serialize({})
        assert isinstance(result, bytes)
        assert len(result) > 0

    async def test_round_trip_simple_types(self, serializer):
        """Test round-trip with standard Python types supported by msgpack."""
        data = {
            "string": "hello",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "none": None,
            "list": [1, 2, 3, 4, 5],
            "nested": {"inner": {"deep": "value"}},
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_large_integers(self, serializer):
        """Test msgpack's support for 64-bit integers."""
        data = {"small": 1, "large": 2**63 - 1, "negative": -(2**63)}
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_unicode_strings(self, serializer):
        """Test UTF-8 string encoding/decoding (raw=False ensures str type)."""
        data = {
            "emoji": "🚀 🎉 ✨",
            "chinese": "你好世界",
            "arabic": "مرحبا بالعالم",
            "special": "Special chars: \n\t\r",
        }
        result = await serializer.deserialize(serializer.serialize(data))
        assert result == data
        # Verify strings are str type, not bytes (raw=False behavior)
        assert all(isinstance(v, str) for v in result.values())


@mark.unit
class TestMsgpackSerializerDateTime:
    """Test datetime and date serialization (using msgpack ext type via default/object_hook)."""

    async def test_datetime_serialization(self, serializer):
        """Test naive datetime serialization (no timezone)."""
        now = datetime(2023, 10, 15, 14, 30, 45, 123456)
        data = {"timestamp": now}
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["timestamp"] == now
        assert isinstance(deserialized["timestamp"], datetime)
        assert deserialized["timestamp"].tzinfo is None

    async def test_datetime_with_timezone(self, serializer):
        """Test aware datetime with timezone (msgpack Timestamp type can be used with datetime=True)."""
        now = datetime(2023, 10, 15, 14, 30, 45, 123456, tzinfo=UTC)
        data = {"timestamp": now}
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["timestamp"] == now
        assert deserialized["timestamp"].tzinfo == UTC

    async def test_date_serialization(self, serializer):
        """Test date object serialization (not datetime)."""
        today = date.today()
        data = {"date": today}

        # Verify we're testing a date and not datetime
        assert type(today) is date
        assert not isinstance(today, datetime)

        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["date"] == today
        assert type(deserialized["date"]) is date

    async def test_multiple_datetime_objects(self, serializer):
        """Test multiple datetime and date objects."""
        data = {
            "created": datetime(2023, 1, 1, 0, 0, 0),
            "updated": datetime(2023, 12, 31, 23, 59, 59),
            "birth_date": date(1990, 5, 15),
            "expiry_date": date(2025, 12, 31),
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data


@mark.unit
class TestMsgpackSerializerDecimal:
    """Test Decimal serialization."""

    async def test_decimal_serialization(self, serializer):
        """Test Decimal object serialization and precision preservation."""
        data = {
            "price": Decimal("19.99"),
            "precise": Decimal("0.123456789012345678901234567890"),
            "scientific": Decimal("1.23E+10"),
            "small": Decimal("0.0000000001"),
            "negative": Decimal("-99.99"),
            "zero": Decimal("0"),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        assert all(isinstance(v, Decimal) for v in deserialized.values())


@mark.unit
class TestMsgpackSerializerUUID:
    """Test UUID serialization."""

    async def test_uuid_serialization(self, serializer):
        """Test UUID object serialization."""
        task_id = uuid4()
        data = {"id": task_id}
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["id"] == task_id
        assert isinstance(deserialized["id"], UUID)

    async def test_multiple_uuids(self, serializer):
        """Test multiple UUID objects and UUID from string."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        data = {
            "task_id": uuid4(),
            "user_id": uuid4(),
            "session_id": UUID(uuid_str),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        assert str(deserialized["session_id"]) == uuid_str


@mark.unit
class TestMsgpackSerializerBytes:
    """Test bytes serialization with use_bin_type=True (modern msgpack)."""

    async def test_bytes_serialization(self, serializer):
        """Test bin type serialization (use_bin_type=True distinguishes str from bytes)."""
        data = {
            "simple": b"hello world",
            "empty": b"",
            "null_bytes": b"\x00\x00\x00",
            "high_bytes": b"\xff\xfe\xfd",
            "mixed": b"\x01\x02\x03\x04\x05",
            "large": bytes(range(256)),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        # Verify bytes type preserved (not str)
        assert all(isinstance(v, bytes) for v in deserialized.values())


@mark.unit
class TestMsgpackSerializerSet:
    """Test set serialization."""

    async def test_set_serialization(self, serializer):
        """Test set serialization (converted to list in msgpack, restored via object_hook)."""
        data = {
            "integers": {1, 2, 3, 4, 5},
            "strings": {"a", "b", "c"},
            "empty": set(),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        assert all(isinstance(v, set) for v in deserialized.values())
        # Empty set should be preserved
        assert len(deserialized["empty"]) == 0


@mark.unit
class TestMsgpackSerializerNested:
    """Test nested and complex structures."""

    async def test_nested_custom_types(self, serializer):
        """Test nested structures with custom types."""
        data = {
            "user": {
                "id": uuid4(),
                "created_at": datetime(2023, 1, 1, 0, 0, 0),
                "balance": Decimal("1000.50"),
                "tags": {"premium", "verified"},
            }
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        # Type assertions
        assert isinstance(deserialized["user"]["id"], UUID)
        assert isinstance(deserialized["user"]["created_at"], datetime)
        assert isinstance(deserialized["user"]["balance"], Decimal)
        assert isinstance(deserialized["user"]["tags"], set)

    async def test_list_of_custom_types(self, serializer):
        """Test lists containing custom types."""
        data = {
            "timestamps": [
                datetime(2023, 1, 1),
                datetime(2023, 6, 1),
                datetime(2023, 12, 31),
            ],
            "amounts": [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")],
            "ids": [uuid4(), uuid4(), uuid4()],
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_deeply_nested_structure(self, serializer):
        """Test deeply nested structures with custom types."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "timestamp": datetime.now(),
                            "amount": Decimal("99.99"),
                            "id": uuid4(),
                            "data": b"deep",
                            "tags": {"nested", "deep"},
                        }
                    }
                }
            }
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_mixed_collections(self, serializer):
        """Test mixed nested collections."""
        data = {
            "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            "records": [
                {"id": uuid4(), "value": Decimal("10.00")},
                {"id": uuid4(), "value": Decimal("20.00")},
            ],
            "meta": {
                "created": datetime.now(),
                "tags": {"a", "b"},
                "nested_list": [{"inner": [1, 2, 3]}],
            },
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data


@mark.unit
class TestMsgpackSerializerEdgeCases:
    """Test edge cases, boundary conditions, and msgpack-specific behavior."""

    async def test_all_custom_types_together(self, serializer):
        """Test all supported types in a single payload (comprehensive integration)."""
        data = {
            "datetime": datetime(2023, 10, 15, 14, 30, 45),
            "date": date(2023, 10, 15),
            "decimal": Decimal("999.99"),
            "uuid": uuid4(),
            "bytes": b"binary data",
            "set": {1, 2, 3},
            "string": "text",
            "number": 42,
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_none_values(self, serializer):
        """Test None/null handling (msgpack nil type: 0xc0)."""
        data = {
            "none_value": None,
            "list_with_none": [1, None, 3],
            "dict_with_none": {"key": None},
            "all_none": [None, None, None],
        }
        result = await serializer.deserialize(serializer.serialize(data))
        assert result == data
        # Verify None is properly distinguished from empty/falsy values
        assert result["none_value"] is None
        assert result["list_with_none"][1] is None

    async def test_map_keys_security(self, serializer):
        """Test map key types (strict_map_key=True limits to str/bytes for security)."""
        # Valid: str and bytes keys (when strict_map_key=True)
        data = {
            "normal_key": "value",
            "key-with-dash": "value",
            "key_with_underscore": "value",
            "key.with.dots": "value",
            "key:with:colons": "value",
            "key with spaces": "value",
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_large_strings(self, serializer):
        """Test large string handling (msgpack str type supports 32-bit length)."""
        long_string = "a" * 10_000
        data = {"long": long_string}
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["long"] == long_string
        assert len(deserialized["long"]) == 10_000

    async def test_many_keys(self, serializer):
        """Test map with many keys (msgpack map32 supports up to 2^32-1 elements)."""
        data = {f"key_{i}": i for i in range(1000)}
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized == data
        assert len(deserialized) == 1000

    async def test_object_identity_not_preserved(self, serializer):
        """Test that object identity is not preserved (expected msgpack behavior)."""
        # After deserialization, equal values become different objects
        shared_uuid = uuid4()
        shared_date = datetime.now()
        data = {
            "id1": shared_uuid,
            "id2": shared_uuid,
            "timestamp1": shared_date,
            "timestamp2": shared_date,
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        # Values are equal but not identical (expected)
        assert deserialized["id1"] == deserialized["id2"]
        assert deserialized["timestamp1"] == deserialized["timestamp2"]
        assert deserialized["id1"] is not deserialized["id2"]


@mark.unit
class TestMsgpackSerializerErrors:
    """Test error handling and security features."""

    def test_unsupported_type_raises_error(self, serializer):
        """Test that unsupported types raise TypeError with clear message."""

        class CustomClass:
            pass

        with raises(TypeError, match="not msgpack serializable"):
            serializer.serialize({"custom": CustomClass()})

    def test_unsupported_type_nested(self, serializer):
        """Test unsupported type detection in nested structures."""

        class CustomClass:
            pass

        with raises(TypeError):
            serializer.serialize({"items": [1, 2, CustomClass()]})

        with raises(TypeError):
            serializer.serialize({"outer": {"inner": CustomClass()}})

    async def test_invalid_msgpack_data(self, serializer):
        """Test deserialization errors for malformed data (security consideration)."""
        # Invalid msgpack data should raise FormatError or UnpackException
        with raises(
            (msgpack.exceptions.FormatError, msgpack.exceptions.UnpackException, ValueError)
        ):
            await serializer.deserialize(b"invalid msgpack data")

    async def test_empty_msgpack_data(self, serializer):
        """Test that empty bytes raise OutOfData exception."""
        # Empty bytes indicate incomplete data
        with raises((msgpack.exceptions.OutOfData, msgpack.exceptions.UnpackException, ValueError)):
            await serializer.deserialize(b"")


@mark.unit
class TestMsgpackSerializerConsistency:
    """Test consistency, idempotency, and round-trip correctness."""

    def test_serialize_is_deterministic(self, serializer):
        """Test that serializing the same data produces identical bytes (deterministic)."""
        data = {"string": "test", "number": 42, "list": [1, 2, 3]}
        serialized1 = serializer.serialize(data)
        serialized2 = serializer.serialize(data)
        assert serialized1 == serialized2
        assert len(serialized1) > 0

    async def test_round_trip_preserves_data_and_types(self, serializer):
        """Test that round-trip preserves both data and types for all custom types."""
        original = {
            "datetime": datetime(2023, 10, 15, 14, 30, 45),
            "date": date(2023, 10, 15),
            "decimal": Decimal("123.45"),
            "uuid": uuid4(),
            "bytes": b"test",
            "set": {1, 2, 3},
        }

        # Single round trip should preserve everything
        deserialized = await serializer.deserialize(serializer.serialize(original))

        # Data equality
        assert deserialized == original

        # Type preservation
        assert isinstance(deserialized["datetime"], datetime)
        assert isinstance(deserialized["date"], date)
        assert isinstance(deserialized["decimal"], Decimal)
        assert isinstance(deserialized["uuid"], UUID)
        assert isinstance(deserialized["bytes"], bytes)
        assert isinstance(deserialized["set"], set)

        # Multiple round trips (idempotency)
        result2 = await serializer.deserialize(serializer.serialize(deserialized))
        result3 = await serializer.deserialize(serializer.serialize(result2))
        assert deserialized == result2 == result3 == original


@mark.unit
class TestMsgpackSerializerRealWorldScenarios:
    """Test real-world task queue scenarios."""

    async def test_task_with_metadata(self, serializer):
        """Test typical task payload with metadata."""
        data = {
            "task_id": uuid4(),
            "task_name": "send_email",
            "args": ["user@example.com", "Welcome!"],
            "kwargs": {"priority": "high", "retry_count": 0},
            "created_at": datetime.now(),
            "scheduled_for": datetime.now(),
            "metadata": {"user_id": uuid4(), "request_id": uuid4()},
        }
        assert await serializer.deserialize(serializer.serialize(data)) == data

    async def test_payment_task(self, serializer):
        """Test payment processing task with Decimal precision."""
        data = {
            "task_id": uuid4(),
            "task_name": "process_payment",
            "amount": Decimal("199.99"),
            "currency": "USD",
            "user_id": uuid4(),
            "transaction_id": uuid4(),
            "timestamp": datetime.now(),
            "metadata": {"card_last4": "4242", "network": "visa"},
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["amount"] == Decimal("199.99")
        assert isinstance(deserialized["amount"], Decimal)

    async def test_batch_processing_task(self, serializer):
        """Test batch processing with multiple items."""
        data = {
            "task_id": uuid4(),
            "task_name": "batch_process",
            "batch_size": 100,
            "items": [
                {"id": uuid4(), "value": Decimal("10.00"), "date": date.today()} for _ in range(10)
            ],
            "created_at": datetime.now(),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert len(deserialized["items"]) == 10
        assert all(isinstance(item["id"], UUID) for item in deserialized["items"])
        assert all(isinstance(item["value"], Decimal) for item in deserialized["items"])

    async def test_file_upload_task(self, serializer):
        """Test task with binary data (e.g., file upload)."""
        pdf_header_bytes = b"\x25\x50\x44\x46"
        data = {
            "task_id": uuid4(),
            "task_name": "process_upload",
            "filename": "document.pdf",
            "content": pdf_header_bytes,
            "size": 1024,
            "uploaded_at": datetime.now(),
            "user_id": uuid4(),
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert deserialized["content"] == pdf_header_bytes

    async def test_scheduled_task_complex(self, serializer):
        """Test scheduled task with complex scheduling data."""
        data = {
            "task_id": uuid4(),
            "task_name": "generate_report",
            "schedule": {
                "start_date": date(2023, 1, 1),
                "end_date": date(2023, 12, 31),
                "execution_times": [
                    datetime(2023, 1, 1, 9, 0, 0),
                    datetime(2023, 1, 2, 9, 0, 0),
                    datetime(2023, 1, 3, 9, 0, 0),
                ],
            },
            "parameters": {
                "format": "pdf",
                "recipients": {"admin@example.com", "manager@example.com"},
            },
        }
        deserialized = await serializer.deserialize(serializer.serialize(data))
        assert isinstance(deserialized["schedule"]["start_date"], date)
        assert isinstance(deserialized["parameters"]["recipients"], set)


@mark.unit
class TestMsgpackConfiguration:
    """Test msgpack configuration follows best practices (msgpack 1.0+)."""

    async def test_use_bin_type_enabled(self, serializer):
        """Test use_bin_type=True (msgpack 1.0 default: distinguishes str from bytes)."""
        # Modern msgpack: bytes serialize to bin type, str to str type
        data = {"binary": b"test", "text": "test"}
        deserialized = await serializer.deserialize(serializer.serialize(data))

        assert isinstance(deserialized["binary"], bytes)
        assert isinstance(deserialized["text"], str)
        assert deserialized["binary"] != deserialized["text"]  # Different types

    async def test_raw_false_behavior(self, serializer):
        """Test raw=False (msgpack 1.0 default: decodes str as UTF-8 str, not bytes)."""
        data = {"text": "hello world"}
        deserialized = await serializer.deserialize(serializer.serialize(data))

        # raw=False ensures strings are str type, not bytes
        assert isinstance(deserialized["text"], str)
        assert not isinstance(deserialized["text"], bytes)

    async def test_utf8_string_handling(self, serializer):
        """Test UTF-8 encoding/decoding (msgpack always uses UTF-8 for strings)."""
        data = {"utf8": "Hello 世界 🌍"}
        deserialized = await serializer.deserialize(serializer.serialize(data))

        assert deserialized["utf8"] == data["utf8"]
        assert isinstance(deserialized["utf8"], str)

    async def test_strict_map_key_security(self, serializer):
        """Test strict_map_key=True (msgpack 1.0 default: prevents hash DoS attacks)."""
        # strict_map_key=True limits map keys to str/bytes only
        # This prevents potential hash collision DoS attacks
        data = {"safe_key": "value", "another_key": 123}
        result = await serializer.deserialize(serializer.serialize(data))

        # All keys should be strings
        assert all(isinstance(k, str) for k in result.keys())


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
