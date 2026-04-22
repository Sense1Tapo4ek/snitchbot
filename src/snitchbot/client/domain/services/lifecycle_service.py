"""Lifecycle event builder service — Task 4.8.

Builds lifecycle/startup and lifecycle/shutdown event dicts ready for send_event.
Module-level mutable state (_sent_shutdown_event) is an acknowledged exception
to immutability (spec CI18/CI34).

Invariants:
- E2: lifecycle severity is None
- CI18: second build_shutdown_event call is a no-op (dedup)
- CI33: startup has phase='startup', reason='init'
- CI34: first shutdown call sets _sent_shutdown_event flag
"""
import os
import threading
import time

from snitchbot import __version__
from snitchbot.shared.domain import EventKind

# Module-level mutable state — acknowledged exception to immutability (CI18, CI34)
_lock = threading.Lock()
_sent_shutdown_event: bool = False
_role: str = "standalone"

def build_startup_event(*, service: str, role: str = "standalone") -> dict:
    """Build a lifecycle/startup event dict ready for send_event.

    Returns a standard envelope with:
    - v=1, ts (wall-clock float), kind='lifecycle', severity=None
    - pid, trace_id=None, context=None
    - payload: {phase='startup', reason='init', exit_code=None, role=role}
    """
    global _role
    _role = role
    return {
        "v": __version__,
        "ts": time.time(),
        "kind": EventKind.LIFECYCLE.value,
        "severity": None,
        "pid": os.getpid(),
        "trace_id": None,
        "context": None,
        "payload": {
            "phase": "startup",
            "reason": "init",
            "exit_code": None,
            "role": role,
        },
    }

def build_shutdown_event(
    *,
    reason: str,
    exit_code: int | None = None,
) -> dict | None:
    """Build a lifecycle/shutdown event dict.

    Sets _sent_shutdown_event flag on first call (CI34).
    Second call is a no-op and returns None (CI18 — dedup).
    """
    global _sent_shutdown_event

    with _lock:
        if _sent_shutdown_event:
            return None  # CI18: dedup, only one shutdown event per process lifetime
        _sent_shutdown_event = True  # CI34

    return {
        "v": __version__,
        "ts": time.time(),
        "kind": EventKind.LIFECYCLE.value,
        "severity": None,
        "pid": os.getpid(),
        "trace_id": None,
        "context": None,
        "payload": {
            "phase": "shutdown",
            "reason": reason,
            "exit_code": exit_code,
            "role": _role,
        },
    }

def reset_lifecycle_state() -> None:
    """Reset lifecycle module state.

    Use for fork safety and in tests to restore clean state.
    """
    global _sent_shutdown_event, _role
    with _lock:
        _sent_shutdown_event = False
        _role = "standalone"
