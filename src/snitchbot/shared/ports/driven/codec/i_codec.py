"""Driven port: msgpack codec interface.

Pure typing only — no framework imports. The concrete implementation lives in
``snitchbot.shared.adapters.driven.codec.msgpack_codec``.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class IMsgpackCodec(Protocol):
    """Serialize event dicts to bytes and back.

    Implementations MUST wrap raw serializer errors into a ``PortError``
    subclass so that no framework exception escapes the port boundary.
    """

    def pack(self, event: dict) -> bytes: ...

    def unpack(self, data: bytes) -> dict: ...

    def size_of(self, event: dict) -> int: ...
