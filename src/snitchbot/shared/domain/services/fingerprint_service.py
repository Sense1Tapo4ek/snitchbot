"""Deterministic fingerprint computation for dedup grouping.

Pure stdlib. No mutation. No I/O. Returns a stable 6-character lowercase
hex string derived from ``blake2b(digest_size=3)`` over
``repr(key).encode("utf-8")`` where ``key`` is a per-kind Python tuple.

Per-kind keys:

- ``crash``: ``(exception_type, tuple((f.file, f.func) for f in top_3_user_frames))``
  where top-3 user frames are the first 3 frames with ``is_user_code=True``.
  ``line`` and ``message`` are intentionally excluded.
- ``custom``: ``(text, caller.file, caller.line)`` — read from ``payload.caller``.
- ``slow_call``: ``func_qualname`` only.
- ``watchdog``: ``("watchdog", stuck_tasks[0].coro)`` if non-empty, else
  ``("watchdog", "generic")``.
- ``anomaly``: ``("anomaly", anomaly_type)``.
- ``lifecycle``: returns ``None`` — never dedup'd.
"""
import hashlib
from typing import TYPE_CHECKING

from ..event_kind_vo import EventKind

if TYPE_CHECKING:
    from ..event_agg import Event

_DIGEST_SIZE = 3  # 3 bytes -> 6 hex chars

def _hash(key: object) -> str:
    """Hash a Python ``key`` per spec §6: ``blake2b(repr(key).encode())``."""
    return hashlib.blake2b(
        repr(key).encode("utf-8"), digest_size=_DIGEST_SIZE
    ).hexdigest()

def compute_fingerprint(event: "Event | dict") -> str | None:
    """Return a stable 6-char hex fingerprint for dedup grouping.

    Accepts either an Event aggregate or a raw dict (from msgpack decode).
    Returns ``None`` for lifecycle events (invariant D7).
    """
    if isinstance(event, dict):
        return _compute_fingerprint_dict(event)
    return _compute_fingerprint_aggregate(event)

def _compute_fingerprint_aggregate(event: "Event") -> str | None:
    """Fingerprint from a typed Event aggregate."""
    kind = event.kind
    payload = event.payload

    if kind is EventKind.LIFECYCLE:
        return None

    if kind is EventKind.CRASH:
        user_frames = tuple(
            f for f in payload.stack if f.is_user_code  # type: ignore[union-attr]
        )[:3]
        key: object = (
            payload.exception_type,  # type: ignore[union-attr]
            tuple((f.file, f.func) for f in user_frames),
        )
        return _hash(key)

    if kind is EventKind.CUSTOM:
        caller = payload.caller  # type: ignore[union-attr]
        caller_file = caller.file if caller is not None else ""
        caller_line = caller.line if caller is not None else 0
        key = (
            payload.text,  # type: ignore[union-attr]
            caller_file,
            caller_line,
        )
        return _hash(key)

    if kind is EventKind.SLOW_CALL:
        return _hash(payload.func_qualname)  # type: ignore[union-attr]

    if kind is EventKind.WATCHDOG:
        tasks = payload.stuck_tasks  # type: ignore[union-attr]
        if tasks:
            key = ("watchdog", tasks[0].coro)
        else:
            key = ("watchdog", "generic")
        return _hash(key)

    if kind is EventKind.ANOMALY:
        key = ("anomaly", payload.anomaly_type)  # type: ignore[union-attr]
        return _hash(key)

    return None

def _compute_fingerprint_dict(event: dict) -> str | None:
    """Fingerprint from a raw dict (msgpack-decoded on sidecar side)."""
    kind = event.get("kind", "")
    payload = event.get("payload") or {}

    if kind == "lifecycle":
        return None

    if kind == "crash":
        stack = payload.get("stack", [])
        user_frames = tuple(
            f for f in stack if (f.get("is_user_code") if isinstance(f, dict) else False)
        )[:3]
        key: object = (
            payload.get("exception_type", ""),
            tuple((f.get("file", ""), f.get("func", "")) for f in user_frames),
        )
        return _hash(key)

    if kind == "custom":
        caller = payload.get("caller") or {}
        caller_file = caller.get("file", "") if isinstance(caller, dict) else ""
        caller_line = caller.get("line", 0) if isinstance(caller, dict) else 0
        key = (
            payload.get("text", ""),
            caller_file,
            caller_line,
        )
        return _hash(key)

    if kind == "slow_call":
        return _hash(payload.get("func_qualname", ""))

    if kind == "watchdog":
        tasks = payload.get("stuck_tasks", [])
        if tasks and isinstance(tasks[0], dict):
            key = ("watchdog", tasks[0].get("coro", ""))
        else:
            key = ("watchdog", "generic")
        return _hash(key)

    if kind == "anomaly":
        key = ("anomaly", payload.get("anomaly_type", ""))
        return _hash(key)

    return None
