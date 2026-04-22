"""Custom payload VO.

Additional spec: ``docs/superpowers/specs/2026-04-11-logging-integration-design.md``
invariant L6 — ``source`` field.

Note on ``extras`` mutability: since Python dicts are inherently mutable, the
frozen dataclass cannot structurally prevent mutation of the inner dict.
Callers should pass an already-immutable mapping (e.g. ``MappingProxyType``)
if strict immutability is required. The validation service only checks type.
"""
from dataclasses import dataclass
from typing import Any, Literal

CustomSource = Literal["notify", "logging", "structlog"]

@dataclass(frozen=True, slots=True, kw_only=True)
class Caller:
    """Call-site coordinates for a ``custom`` event (spec §4.2)."""

    file: str
    line: int
    func: str

@dataclass(frozen=True, slots=True, kw_only=True)
class CustomPayload:
    """Payload for ``EventKind.CUSTOM`` events.

    ``source`` default ``None`` means the caller did not specify a source;
    downstream code treats an absent/None source as ``"notify"`` (L6).
    ``caller`` captures the notify() call site (spec §4.2) and feeds the
    custom fingerprint (spec §6).
    """

    text: str
    extras: dict[str, Any] | None
    exception: dict[str, Any] | None
    source: CustomSource | None = None
    caller: Caller | None = None
