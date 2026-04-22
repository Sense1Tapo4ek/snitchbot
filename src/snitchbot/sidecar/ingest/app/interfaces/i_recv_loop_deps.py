"""Protocols for RecvLoop cross-context dependencies.

RecvLoop (ingest/adapters/driving) depends on components from other bounded
contexts. These Protocols define the minimal surface used — no concrete
imports from those contexts.
"""
from collections.abc import Callable
from typing import Protocol

__all__ = [
    "ICodec",
    "IRegisterClientUC",
    "IEventQueue",
    "IDedupCache",
    "ISidecarSession",
    "IRecentBuffer",
    "EnqueueFn",
    "FingerprintFn",
]

# Type alias for the fingerprint callable
FingerprintFn = Callable[[dict], "str | None"]

# Callable injected at composition time: (event, fingerprint) -> (accepted, action, enriched)
EnqueueFn = Callable[[dict, "str | None"], "tuple[bool, str, dict]"]


class ICodec(Protocol):
    """Encode/decode datagrams."""

    def pack(self, obj: object) -> bytes: ...
    def unpack(self, data: bytes) -> dict: ...


class IRegisterClientUC(Protocol):
    """Sync callable: process hello dict, return ack/reject dict."""

    def __call__(self, *, hello: dict, sender_addr: str) -> dict: ...


class IEventQueue(Protocol):
    """Central event queue — enqueue items."""

    def enqueue(self, item: object) -> bool: ...


class IDedupCache(Protocol):
    """Dedup cache — classify events and retrieve entries."""

    def classify(
        self,
        *,
        fingerprint: str,
        severity: str | None,
        event: dict,
        now: float,
    ) -> str: ...

    def get_entry(self, fingerprint: str) -> object | None: ...


class ISidecarSession(Protocol):
    """Minimal session surface used by ingest context."""

    first_hello_received: bool
    def mark_activity(self) -> None: ...
    def mark_first_hello(self) -> None: ...


class IRecentBuffer(Protocol):
    """Recent-events buffer — append new events."""

    def add(self, event: object) -> None: ...
