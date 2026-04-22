"""Driven codec adapter — public API."""

from snitchbot.shared.adapters.driven.codec.msgpack_codec import (
    CodecError,
    MsgpackCodec,
)

__all__ = ["CodecError", "MsgpackCodec"]
