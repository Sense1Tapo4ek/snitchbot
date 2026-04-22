"""Unit tests for the progressive truncation service (Phase 1 · Task 1.6).

These tests validate spec §7 of `docs/superpowers/specs/2026-04-11-event-model-design.md`:
progressive truncation across 4 ordered steps, and invariant E4 (`MAX_EVENT_SIZE == 8192`).

The domain service is msgpack-free by design: the caller injects a `size_fn`
so the domain layer stays pure stdlib. For tests we use a JSON byte-length
stand-in which gives us a deterministic, controllable byte-count proxy.
"""
import copy
import json

import pytest

from snitchbot import __version__
from snitchbot.shared.constants import MAX_EVENT_SIZE
from snitchbot.shared.domain.services import truncate_if_oversized


# --- helpers ----------------------------------------------------------------


def _size_fn(d: dict) -> int:
    """Deterministic byte-size proxy used as `size_fn` in tests."""
    return len(json.dumps(d, default=str).encode())


def _base_event(**overrides) -> dict:
    """Minimal envelope-complete event. ~200 bytes."""
    event = {
        "v": __version__,
        "ts": 1_700_000_000.0,
        "kind": "crash",
        "severity": "error",
        "pid": 4242,
        "trace_id": "abc123",
        "context": None,
        "payload": {
            "exception_type": "ValueError",
            "message": "something went wrong",
            "stack": [],
            "extras": {},
        },
    }
    event["payload"].update(overrides.pop("payload", {}))
    event.update(overrides)
    return event


def _frame(file="/app/svc.py", line=42, func="do_thing", code="x = compute()"):
    return {"file": file, "line": line, "func": func, "code": code}


# --- tests ------------------------------------------------------------------


class TestTruncationNoOp:
    def test_truncate_noop_when_event_already_fits(self):
        """
        Given an event already below MAX_EVENT_SIZE,
        When truncate_if_oversized is called,
        Then a new dict equal to the original is returned (copy, not same ref).
        """
        # Arrange
        event = _base_event()
        assert _size_fn(event) < MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result == event
        assert result is not event


class TestStep1StripCode:
    def test_truncate_strips_code_first(self):
        """
        Given an oversized event whose bulk is `code` strings in stack frames,
        When truncating,
        Then step 1 strips all frame `code` values and the event fits.
        """
        # Arrange: 50 frames each with a ~300-char `code` -> ~15 KB of code alone.
        big_code = "C" * 300
        frames = [_frame(code=big_code) for _ in range(50)]
        event = _base_event(payload={"stack": frames})
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert: fits, stack preserved in length, every code emptied.
        assert result is not None
        assert _size_fn(result) <= MAX_EVENT_SIZE
        assert len(result["payload"]["stack"]) == 50
        for f in result["payload"]["stack"]:
            assert f.get("code") in ("", None)


class TestStep2DropExtrasLongestFirst:
    def test_truncate_then_extras_longest_keys_first(self):
        """
        Given an oversized event with payload.extras,
        When step 1 doesn't free enough,
        Then step 2 drops entries starting from the longest key.
        """
        # Arrange: no stack code to strip. Extras carry the weight.
        extras = {
            "short": "ok",
            "medium_key": "M" * 100,
            "super_long_key_name_xxx": "L" * 6000,  # dominant -> dropped first
            "another_big_key_yyyy": "B" * 2500,
        }
        event = _base_event(payload={"stack": [], "extras": extras})
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is not None
        assert _size_fn(result) <= MAX_EVENT_SIZE
        remaining = result["payload"]["extras"]
        # Longest key MUST have been dropped first.
        assert "super_long_key_name_xxx" not in remaining
        # Short key should survive (dropped last, if at all).
        assert "short" in remaining


class TestStep3TrimStackBottom:
    def test_truncate_then_stack_from_bottom_keeping_topN(self):
        """
        Given an oversized stack after step 1 (no code) and step 2 (no extras),
        When step 3 trims the stack from the bottom,
        Then the top frames are preserved (bottom frames dropped first).
        """
        # Arrange: 200 frames, each ~120 bytes of non-code metadata.
        frames = [
            _frame(
                file=f"/app/module_{i:03d}/submod.py",
                line=i,
                func=f"function_number_{i:03d}",
                code="",  # already stripped
            )
            for i in range(200)
        ]
        event = _base_event(payload={"stack": frames, "extras": {}})
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is not None
        assert _size_fn(result) <= MAX_EVENT_SIZE
        new_stack = result["payload"]["stack"]
        assert 0 < len(new_stack) < 200
        # Top frames preserved — frame 0 is still there.
        assert new_stack[0]["func"] == "function_number_000"
        # Last kept frame is NOT frame 199 (bottom trimmed).
        assert new_stack[-1]["func"] != "function_number_199"


class TestStep4AggressiveMessage:
    def test_truncate_then_message_aggressive(self):
        """
        Given a small stack/extras but a huge message,
        When steps 1–3 don't release enough,
        Then step 4 aggressively cuts payload.message.
        """
        # Arrange
        event = _base_event(
            payload={
                "message": "M" * 9000,
                "stack": [],
                "extras": {},
            }
        )
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is not None
        assert _size_fn(result) <= MAX_EVENT_SIZE
        # Aggressive cut: message much shorter than the original.
        assert len(result["payload"]["message"]) <= 500


class TestDropWhenStillOversized:
    def test_truncate_drop_if_still_oversized_after_all_steps(self):
        """
        Given an event that cannot be shrunk below the cap even after all 4 steps,
        When truncating,
        Then None is returned and caller increments `oversized` counter.
        """
        # Arrange: envelope fields themselves are bloated — nothing step 1–4 can touch.
        event = _base_event(trace_id="T" * 20000)
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is None


class TestPreservesEnvelope:
    def test_truncate_preserves_required_envelope_fields(self):
        """
        Given an oversized event,
        When truncated,
        Then envelope fields `v, ts, kind, severity, pid, trace_id` are untouched.
        """
        # Arrange
        event = _base_event(
            payload={
                "message": "X" * 9000,
                "stack": [_frame(code="Y" * 400) for _ in range(30)],
                "extras": {"big": "Z" * 2000},
            }
        )
        original_envelope = {
            k: event[k] for k in ("v", "ts", "kind", "severity", "pid", "trace_id")
        }

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is not None
        for k, v in original_envelope.items():
            assert result[k] == v


class TestHardCapConstant:
    def test_size_8KB_hard_cap_constant(self):
        """
        Invariant E4: the hard cap is exactly 8 KiB (8192 bytes).
        """
        assert MAX_EVENT_SIZE == 8192


class TestDeepCopyImmutability:
    def test_truncate_deep_copies_input_not_mutated(self):
        """
        Given an oversized event,
        When truncated,
        Then the original `event_dict` is NOT mutated.
        """
        # Arrange
        event = _base_event(
            payload={
                "stack": [_frame(code="A" * 500) for _ in range(40)],
                "extras": {"k": "V" * 3000},
                "message": "hi",
            }
        )
        snapshot = copy.deepcopy(event)

        # Act
        _ = truncate_if_oversized(event, _size_fn)

        # Assert: original is byte-for-byte unchanged.
        assert event == snapshot


class TestNoStackField:
    def test_truncate_with_no_stack_skips_step1_and_step3(self):
        """
        Given a custom event with no `stack` field,
        When oversized,
        Then truncation still succeeds via step 2 (extras) and step 4 (text).
        """
        # Arrange
        event = _base_event(
            kind="custom",
            payload={
                "text": "T" * 9000,
                "extras": {"big_key_name": "Q" * 2500},
                # no `stack` key at all
            },
        )
        # Remove the stack placeholder that _base_event adds.
        event["payload"].pop("stack", None)
        event["payload"].pop("message", None)

        assert "stack" not in event["payload"]
        assert _size_fn(event) > MAX_EVENT_SIZE

        # Act
        result = truncate_if_oversized(event, _size_fn)

        # Assert
        assert result is not None
        assert _size_fn(result) <= MAX_EVENT_SIZE
        assert "stack" not in result["payload"]
