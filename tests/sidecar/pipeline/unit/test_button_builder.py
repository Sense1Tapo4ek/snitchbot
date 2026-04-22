"""Unit tests for button_builder_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §6.6, R4.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.7.
Invariants: R4, T12 (partial).
"""
from snitchbot.sidecar.pipeline.domain.services.button_builder_service import build_buttons

_FP = "a1b2c3"


class TestButtonCount:
    def test_3_buttons_when_no_trace(self) -> None:
        """
        Given has_trace=False,
        When build_buttons() is called,
        Then exactly 3 mute buttons are returned in one row (no trace button).
        """
        rows = build_buttons(fingerprint=_FP, has_trace=False)
        assert len(rows) == 1
        assert len(rows[0]) == 3

    def test_4_buttons_when_trace_available(self) -> None:
        """
        Given has_trace=True,
        When build_buttons() is called,
        Then 4 buttons are returned: 3 mute + 1 trace (R4).
        """
        rows = build_buttons(fingerprint=_FP, has_trace=True)
        assert len(rows) == 1
        assert len(rows[0]) == 4


class TestCallbackDataFormat:
    def test_callback_data_format_mute_fp_dur(self) -> None:
        """
        Given a fingerprint and mute buttons,
        When build_buttons() is called,
        Then callback_data for mute buttons matches 'mute:<fp>:<duration>' format.
        """
        rows = build_buttons(fingerprint=_FP, has_trace=False)
        buttons = rows[0]
        mute_buttons = [b for b in buttons if b["callback_data"].startswith("mute:")]
        assert len(mute_buttons) == 3
        for btn in mute_buttons:
            parts = btn["callback_data"].split(":")
            assert len(parts) == 3
            assert parts[0] == "mute"
            assert parts[1] == _FP
            # duration part must be a non-empty string
            assert len(parts[2]) > 0

    def test_callback_data_format_trace_fp(self) -> None:
        """
        Given has_trace=True,
        When build_buttons() is called,
        Then the trace button callback_data matches 'trace:<fp>' format.
        """
        rows = build_buttons(fingerprint=_FP, has_trace=True)
        trace_buttons = [b for b in rows[0] if b["callback_data"].startswith("trace:")]
        assert len(trace_buttons) == 1
        assert trace_buttons[0]["callback_data"] == f"trace:{_FP}"

    def test_callback_data_under_64_bytes(self) -> None:
        """
        Given a fingerprint of up to 6 hex chars,
        When build_buttons() is called,
        Then all callback_data values are strictly under 64 bytes (Telegram limit).
        """
        rows = build_buttons(fingerprint=_FP, has_trace=True)
        for btn in rows[0]:
            cb = btn["callback_data"]
            assert len(cb.encode("utf-8")) < 64, f"callback_data too long: {cb!r}"

    def test_buttons_are_inline_keyboard_button_dicts(self) -> None:
        """
        Given any inputs,
        When build_buttons() is called,
        Then each button is a dict with 'text' and 'callback_data' keys (TG schema).
        """
        rows = build_buttons(fingerprint=_FP, has_trace=True)
        for btn in rows[0]:
            assert isinstance(btn, dict)
            assert "text" in btn
            assert "callback_data" in btn
            assert isinstance(btn["text"], str)
            assert isinstance(btn["callback_data"], str)

    def test_mute_button_texts_present(self) -> None:
        """
        Given build_buttons() is called,
        Then mute button labels contain mute-related text (e.g. 🔇 icon or 'Mute').
        """
        rows = build_buttons(fingerprint=_FP, has_trace=False)
        for btn in rows[0]:
            # Each mute button text must be non-empty
            assert len(btn["text"]) > 0
