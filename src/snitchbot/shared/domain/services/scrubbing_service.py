"""Secret scrubbing service.

Pure functions. No I/O, no logging, no global mutable state.
Reference: docs/superpowers/specs/2026-04-11-secret-scrubbing-design.md (§6, §10 S1-S12).
"""
import copy
from typing import Any

from .scrubbing_patterns import (
    KEY_DENYLIST,
    PLACEHOLDER,
    iter_patterns_with_replacement,
)


def scrub_string(s: str) -> str:
    """Apply all regex patterns in order, returning a scrubbed copy.

    Idempotent (S7). Does not mutate input (strings are immutable anyway).
    """
    if not isinstance(s, str):
        return s
    out = s
    for _name, pattern, replacement in iter_patterns_with_replacement():
        out = pattern.sub(replacement, out)
    return out


def _key_matches_denylist(key: str) -> bool:
    """Case-insensitive substring match against the denylist (S4)."""
    key_lower = key.lower()
    return any(token in key_lower for token in KEY_DENYLIST)


def scrub_value(key: str | None, value: Any) -> Any:
    """Scrub a value based on its key and type.

    - If `key` matches the denylist -> PLACEHOLDER (S4).
    - str       -> regex-scrubbed copy.
    - dict      -> recurse, carrying each child key.
    - list/tuple-> recurse element-wise, preserving the concrete type.
    - other     -> passthrough (S8).
    """
    if isinstance(key, str) and _key_matches_denylist(key):
        return PLACEHOLDER

    if isinstance(value, str):
        return scrub_string(value)

    if isinstance(value, dict):
        return {k: scrub_value(k if isinstance(k, str) else None, v) for k, v in value.items()}

    if isinstance(value, list):
        return [scrub_value(None, item) for item in value]

    if isinstance(value, tuple):
        return tuple(scrub_value(None, item) for item in value)

    # Numbers, bools, None, and unknown types pass through untouched (S8).
    return value


def _scrub_dict_only(d: dict) -> dict:
    """Recursively scrub a dict's string values (used for context/extras)."""
    return {k: scrub_value(k if isinstance(k, str) else None, v) for k, v in d.items()}


def _scrub_crash_payload(payload: dict) -> None:
    """In-place scrub of a crash payload (operates on the deep copy)."""
    if isinstance(payload.get("message"), str):
        payload["message"] = scrub_string(payload["message"])
    stack = payload.get("stack")
    if isinstance(stack, list):
        for frame in stack:
            if isinstance(frame, dict) and isinstance(frame.get("code"), str):
                frame["code"] = scrub_string(frame["code"])


def _scrub_custom_payload(payload: dict) -> None:
    """In-place scrub of a custom payload (operates on the deep copy)."""
    if isinstance(payload.get("text"), str):
        payload["text"] = scrub_string(payload["text"])
    extras = payload.get("extras")
    if isinstance(extras, dict):
        payload["extras"] = _scrub_dict_only(extras)
    exc = payload.get("exception")
    if isinstance(exc, dict):
        if isinstance(exc.get("message"), str):
            exc["message"] = scrub_string(exc["message"])
        exc_stack = exc.get("stack")
        if isinstance(exc_stack, list):
            for frame in exc_stack:
                if isinstance(frame, dict) and isinstance(frame.get("code"), str):
                    frame["code"] = scrub_string(frame["code"])


def _scrub_watchdog_payload(payload: dict) -> None:
    """In-place scrub of a watchdog payload (operates on the deep copy)."""
    stuck = payload.get("stuck_tasks")
    if isinstance(stuck, list):
        for task in stuck:
            if not isinstance(task, dict):
                continue
            task_stack = task.get("stack")
            if isinstance(task_stack, list):
                task["stack"] = [
                    scrub_string(item) if isinstance(item, str) else item
                    for item in task_stack
                ]


def scrub_event(event: dict) -> dict:
    """Return a deep-copied event with scrubbed fields per kind (spec §6, §7).

    Invariant S2: the input event is not mutated.
    """
    clean = copy.deepcopy(event)

    # Context is always scrubbed recursively if present.
    ctx = clean.get("context")
    if isinstance(ctx, dict):
        clean["context"] = _scrub_dict_only(ctx)

    kind = clean.get("kind")
    payload = clean.get("payload")

    if isinstance(payload, dict):
        if kind == "crash":
            _scrub_crash_payload(payload)
        elif kind == "custom":
            _scrub_custom_payload(payload)
        elif kind == "watchdog":
            _scrub_watchdog_payload(payload)
        # slow_call, anomaly, lifecycle: payload left untouched (spec §7).

    return clean


__all__ = ["scrub_string", "scrub_value", "scrub_event"]
