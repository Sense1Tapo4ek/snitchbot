"""Unit tests for the msgpack codec (Task 1.7).

Pure-CPU tests — no mocks, no I/O. Verifies:
- roundtrip fidelity for valid dicts (including nested structures and binary)
- non-dict payloads are rejected on unpack
- ``size_of`` matches ``len(pack(...))``
- all raw msgpack errors are wrapped in ``CodecError``
- ``CodecError`` is a ``PortError`` subclass
- the concrete codec is compatible with the ``IMsgpackCodec`` protocol
"""

import pytest

from snitchbot.shared.adapters.driven.codec import CodecError, MsgpackCodec
from snitchbot.shared.generics.errors import PortError
from snitchbot.shared.ports.driven.codec import IMsgpackCodec


@pytest.fixture
def codec() -> MsgpackCodec:
    return MsgpackCodec()


class TestRoundtrip:
    def test_codec_roundtrip_valid_event(self, codec: MsgpackCodec) -> None:
        """
        Given a simple event dict,
        When packing and then unpacking,
        Then the original dict is recovered exactly.
        """
        event = {"type": "click", "user_id": 42, "ok": True}
        packed = codec.pack(event)
        unpacked = codec.unpack(packed)
        assert unpacked == event

    def test_codec_roundtrip_preserves_nested_structures(
        self, codec: MsgpackCodec
    ) -> None:
        """
        Given an event with nested dicts, lists, ints, floats, and strings,
        When round-tripping through the codec,
        Then every nested value is preserved.
        """
        event = {
            "name": "nested",
            "count": 7,
            "ratio": 1.5,
            "tags": ["a", "b", "c"],
            "meta": {
                "inner": {"x": 1, "y": [2, 3, 4]},
                "flag": False,
            },
        }
        assert codec.unpack(codec.pack(event)) == event

    def test_codec_roundtrip_empty_dict(self, codec: MsgpackCodec) -> None:
        """
        Given an empty dict,
        When packing and unpacking,
        Then an empty dict is returned.
        """
        assert codec.unpack(codec.pack({})) == {}

    def test_codec_handles_binary_values(self, codec: MsgpackCodec) -> None:
        """
        Given an event containing bytes values,
        When round-tripping,
        Then bytes are preserved (use_bin_type=True).
        """
        event = {"blob": b"\x00\x01\x02\xff", "label": "binary"}
        recovered = codec.unpack(codec.pack(event))
        assert recovered == event
        assert isinstance(recovered["blob"], bytes)


class TestTypes:
    def test_codec_pack_returns_bytes(self, codec: MsgpackCodec) -> None:
        """Given any valid event, when packing, then a bytes object is returned."""
        assert isinstance(codec.pack({"k": "v"}), bytes)

    def test_codec_unpack_returns_dict(self, codec: MsgpackCodec) -> None:
        """Given a packed dict, when unpacking, then a dict is returned."""
        result = codec.unpack(codec.pack({"k": "v"}))
        assert isinstance(result, dict)

    def test_codec_size_matches_packb_len(self, codec: MsgpackCodec) -> None:
        """Given an event, when asking for size_of, then it equals len(pack(...))."""
        event = {"type": "msg", "payload": [1, 2, 3], "s": "hello"}
        assert codec.size_of(event) == len(codec.pack(event))


class TestErrors:
    def test_codec_rejects_non_dict_on_unpack(self, codec: MsgpackCodec) -> None:
        """
        Given bytes that decode to a non-dict value,
        When unpacking,
        Then CodecError is raised.
        """
        import msgpack  # local — only to build the adversarial input

        payload = msgpack.packb(123, use_bin_type=True)
        with pytest.raises(CodecError):
            codec.unpack(payload)

    def test_codec_raises_codec_error_on_unpackable_value(
        self, codec: MsgpackCodec
    ) -> None:
        """
        Given a dict containing a value msgpack cannot serialize,
        When packing,
        Then CodecError is raised (raw msgpack error never escapes).
        """
        class NotSerializable:
            pass

        with pytest.raises(CodecError):
            codec.pack({"bad": NotSerializable()})

    def test_codec_error_is_port_error(self) -> None:
        """CodecError must inherit from PortError per S-DDD error hierarchy."""
        assert issubclass(CodecError, PortError)


class TestProtocolCompatibility:
    def test_codec_implements_protocol(self, codec: MsgpackCodec) -> None:
        """
        Given a MsgpackCodec instance,
        When checking against IMsgpackCodec,
        Then it is recognised as a structural implementation.
        """
        # runtime_checkable Protocol — isinstance is the structural check.
        assert isinstance(codec, IMsgpackCodec)
        # Belt-and-braces: the three methods must exist and be callable.
        assert callable(getattr(codec, "pack", None))
        assert callable(getattr(codec, "unpack", None))
        assert callable(getattr(codec, "size_of", None))
