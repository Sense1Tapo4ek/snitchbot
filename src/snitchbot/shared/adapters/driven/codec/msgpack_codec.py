"""Concrete msgpack codec adapter.

This module is the ONLY place in the shared kernel allowed to import
``msgpack``. All raw msgpack exceptions are wrapped in :class:`CodecError`
so they never escape the port boundary.
"""

import msgpack

from snitchbot.shared.generics.errors import PortError
from snitchbot.shared.ports.driven.codec.i_codec import IMsgpackCodec


class CodecError(PortError):
    """Raised when packing or unpacking fails (wraps msgpack errors)."""

    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(msg)


class MsgpackCodec(IMsgpackCodec):
    """Pure-CPU codec for serializing event dicts to msgpack bytes."""

    def pack(self, event: dict) -> bytes:
        try:
            return msgpack.packb(event, use_bin_type=True)
        except (msgpack.PackException, TypeError, ValueError) as e:
            raise CodecError(f"pack failed: {e}") from e

    def unpack(self, data: bytes) -> dict:
        try:
            result = msgpack.unpackb(data, raw=False)
        except (msgpack.UnpackException, ValueError) as e:
            raise CodecError(f"unpack failed: {e}") from e
        if not isinstance(result, dict):
            raise CodecError(
                f"unpack produced non-dict: {type(result).__name__}"
            )
        return result

    def size_of(self, event: dict) -> int:
        return len(self.pack(event))
