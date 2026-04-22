"""Progressive event truncation service (pure domain logic).

Implements §7 of `docs/superpowers/specs/2026-04-11-event-model-design.md`:
a 4-step progressive reducer that shrinks an oversized event dict until it
fits under `MAX_EVENT_SIZE`, or returns `None` if it still can't.

Invariant E4: the hard cap is `MAX_EVENT_SIZE == 8192` bytes.

Design notes:
- Pure function. No I/O. No logging. No mutation of the caller's dict.
- Framework-agnostic: the byte-size measurement is injected via `size_fn`
  so this module has no msgpack / json dependency. Driven ports provide the
  real msgpack-based measurement at runtime.
"""
import copy
from collections.abc import Callable

from snitchbot.shared.constants import MAX_EVENT_SIZE

__all__ = ["truncate_if_oversized"]


# Step 3 progression: try keeping the top N frames, dropping the rest from
# the bottom. We start generous (spec §6 caps `stack` at 50 frames) and
# decrease toward an ever-smaller tail.
_STEP3_KEEP_N_SEQUENCE: tuple[int, ...] = (30, 20, 10, 5, 3, 1)

# Step 4 progression: shrink message/text to progressively tighter caps.
_STEP4_MESSAGE_CAPS: tuple[int, ...] = (500, 200, 80, 20)


def truncate_if_oversized(
    event_dict: dict,
    size_fn: Callable[[dict], int],
) -> dict | None:
    """Progressively shrink an oversized event to fit `MAX_EVENT_SIZE`.

    Args:
        event_dict: raw event dict. NOT mutated (the function deep-copies first).
        size_fn: returns byte-size of a packed event. Caller decides the
            serialization (msgpack in prod, json in tests).

    Returns:
        A new dict that fits within `MAX_EVENT_SIZE`, or `None` if even after
        all 4 steps the event still exceeds the cap.

    Steps (per spec §7):
        1. Strip `code` from every stack frame in `payload.stack`.
        2. Drop `payload.extras` entries, longest key first.
        3. Trim `payload.stack` from the bottom, keeping top-N.
        4. Aggressively cut `payload.message` / `payload.text`.
    """
    # Fast path: already fits. Still return a deep copy to keep the contract
    # uniform (caller can safely mutate the result without touching input).
    working = copy.deepcopy(event_dict)
    if size_fn(working) <= MAX_EVENT_SIZE:
        return working

    payload = working.get("payload")
    if not isinstance(payload, dict):
        # Nothing the steps can touch.
        return None

    # --- Step 1: strip `code` from every stack frame -------------------------
    stack = payload.get("stack")
    if isinstance(stack, list):
        for frame in stack:
            if isinstance(frame, dict) and "code" in frame:
                frame["code"] = ""
        if size_fn(working) <= MAX_EVENT_SIZE:
            return working

    # --- Step 2: drop extras, longest key first ------------------------------
    extras = payload.get("extras")
    if isinstance(extras, dict) and extras:
        # Sort keys by length descending; tie-break alphabetically for stability.
        for key in sorted(extras.keys(), key=lambda k: (-len(str(k)), str(k))):
            extras.pop(key, None)
            if size_fn(working) <= MAX_EVENT_SIZE:
                return working

    # --- Step 3: trim stack from the bottom ----------------------------------
    if isinstance(stack, list) and len(stack) > 1:
        for keep_n in _STEP3_KEEP_N_SEQUENCE:
            if keep_n >= len(stack):
                continue
            payload["stack"] = stack[:keep_n]
            stack = payload["stack"]
            if size_fn(working) <= MAX_EVENT_SIZE:
                return working

    # --- Step 4: aggressive message truncation -------------------------------
    # Some events carry `message` (crash), others `text` (custom). Try both.
    for field in ("message", "text"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            continue
        for cap in _STEP4_MESSAGE_CAPS:
            if len(value) <= cap:
                continue
            payload[field] = value[:cap]
            value = payload[field]
            if size_fn(working) <= MAX_EVENT_SIZE:
                return working

    # Still oversized after all four steps -> caller must drop the event.
    return None
