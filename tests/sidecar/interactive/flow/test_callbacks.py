"""Flow tests for CallbackRouter and callback use cases.

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §9, §10.
Plan: Task 9.7.

Invariants validated: T11 (edit source message), T12 (invalid callback),
T13 (edit failure swallowed), RL8.
"""
from unittest.mock import AsyncMock

import pytest

from snitchbot.sidecar.muting.app.use_cases.mute_callback_uc import MuteCallbackUC
from snitchbot.sidecar.muting.app.use_cases.unmute_callback_uc import UnmuteCallbackUC
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState
from snitchbot.sidecar.telegram_io.adapters.driving.callback_router import (
    CallbackParseError,
    CallbackRouter,
    parse_callback_data,
)

_CHAT_ID = "-100123456"
_NOW = 1_000_000.0
_FP = "a1b2c3"


# ---------------------------------------------------------------------------
# parse_callback_data unit tests
# ---------------------------------------------------------------------------

class TestParseCallbackData:
    def test_callback_parses_mute_fp_dur(self) -> None:
        """
        Given "mute:a1b2c3:1h",
        When parsed,
        Then returns ("mute", "a1b2c3", "1h").
        """
        result = parse_callback_data("mute:a1b2c3:1h")
        assert result == ("mute", "a1b2c3", "1h")

    def test_callback_parses_unmute_fp(self) -> None:
        """
        Given "unmute:a1b2c3",
        When parsed,
        Then returns ("unmute", "a1b2c3").
        """
        result = parse_callback_data("unmute:a1b2c3")
        assert result == ("unmute", "a1b2c3")

    def test_callback_parses_trace_fp(self) -> None:
        """
        Given "trace:a1b2c3",
        When parsed,
        Then returns ("trace", "a1b2c3").
        """
        result = parse_callback_data("trace:a1b2c3")
        assert result == ("trace", "a1b2c3")

    def test_invalid_callback_raises(self) -> None:
        """T12: invalid callback_data raises CallbackParseError."""
        with pytest.raises(CallbackParseError):
            parse_callback_data("bogus:data:extra:parts")

    def test_unknown_action_raises(self) -> None:
        """
        Given callback_data with unknown action,
        When parsed,
        Then CallbackParseError raised.
        """
        with pytest.raises(CallbackParseError):
            parse_callback_data("delete:fp123")

    def test_mute_wrong_parts_raises(self) -> None:
        """
        Given "mute:fp" (missing duration),
        When parsed,
        Then CallbackParseError raised.
        """
        with pytest.raises(CallbackParseError):
            parse_callback_data("mute:fp123")


# ---------------------------------------------------------------------------
# CallbackRouter tests
# ---------------------------------------------------------------------------

def _make_router(
    *,
    mute_cb=None,
    unmute_cb=None,
    trace_cb=None,
    gateway=None,
    chat_id: str = _CHAT_ID,
) -> CallbackRouter:
    if mute_cb is None:
        mute_cb = AsyncMock()
    if unmute_cb is None:
        unmute_cb = AsyncMock()
    if trace_cb is None:
        trace_cb = AsyncMock()
    if gateway is None:
        gateway = AsyncMock()
    return CallbackRouter(
        _mute_cb_uc=mute_cb,
        _unmute_cb_uc=unmute_cb,
        _trace_cb_uc=trace_cb,
        _gateway=gateway,
        _chat_id=chat_id,
    )


def _make_cq(data: str, message_id: int = 99, chat_id: str = _CHAT_ID) -> dict:
    return {
        "id": "cq-001",
        "data": data,
        "message": {
            "message_id": message_id,
            "chat": {"id": int(chat_id)},
        },
    }


class TestCallbackRouterDispatch:
    @pytest.mark.asyncio
    async def test_mute_callback_dispatched(self) -> None:
        """
        Given callback_data="mute:a1b2c3:1h",
        When router handles it,
        Then MuteCallbackUC is called with correct args.
        """
        mute_cb = AsyncMock()
        router = _make_router(mute_cb=mute_cb)
        cq = _make_cq("mute:a1b2c3:1h", message_id=55)
        await router.handle(cq)
        mute_cb.assert_called_once()
        kwargs = mute_cb.call_args.kwargs
        assert kwargs["fingerprint"] == "a1b2c3"
        assert kwargs["duration_str"] == "1h"
        assert kwargs["message_id"] == 55

    @pytest.mark.asyncio
    async def test_unmute_callback_dispatched(self) -> None:
        """
        Given callback_data="unmute:a1b2c3",
        When router handles it,
        Then UnmuteCallbackUC is called.
        """
        unmute_cb = AsyncMock()
        router = _make_router(unmute_cb=unmute_cb)
        cq = _make_cq("unmute:a1b2c3")
        await router.handle(cq)
        unmute_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_trace_callback_dispatched(self) -> None:
        """
        Given callback_data="trace:a1b2c3",
        When router handles it,
        Then TraceCallbackUC is called.
        """
        trace_cb = AsyncMock()
        router = _make_router(trace_cb=trace_cb)
        cq = _make_cq("trace:a1b2c3")
        await router.handle(cq)
        trace_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_callback_error_answered(self) -> None:
        """T12: Invalid callback_data is answered with error, not raised.

        Given malformed callback_data,
        When router handles it,
        Then gateway.answer_callback_query called with error text.
        """
        gateway = AsyncMock()
        router = _make_router(gateway=gateway)
        cq = _make_cq("completely_bogus_no_colon_no_action_hmm")
        # Should not raise
        await router.handle(cq)
        gateway.answer_callback_query.assert_called_once()
        call_kwargs = gateway.answer_callback_query.call_args.kwargs
        assert "❌" in call_kwargs.get("text", "") or call_kwargs.get("show_alert")

    @pytest.mark.asyncio
    async def test_answer_callback_not_main_bucket(self) -> None:
        """RL8: answerCallbackQuery does not consume main rate bucket.

        Given a valid callback,
        When router handles it,
        Then answerCallbackQuery is called by the UC directly (not routed through
        command_budget or main rate bucket).
        """
        mute_cb = AsyncMock()
        gateway = AsyncMock()
        router = _make_router(mute_cb=mute_cb, gateway=gateway)
        cq = _make_cq("mute:a1b2c3:1h")
        await router.handle(cq)
        # The main gateway.answer_callback_query is NOT called by the router itself
        # (it's called inside MuteCallbackUC) — so gateway mock on router level
        # should not have been called for answerCallbackQuery
        gateway.answer_callback_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_from_wrong_chat_ignored(self) -> None:
        """T1 variant for callbacks: foreign chat_id is ignored."""
        mute_cb = AsyncMock()
        router = _make_router(mute_cb=mute_cb, chat_id="-100123456")
        cq = _make_cq("mute:a1b2c3:1h", chat_id="-999999")
        await router.handle(cq)
        mute_cb.assert_not_called()


# ---------------------------------------------------------------------------
# MuteCallbackUC tests
# ---------------------------------------------------------------------------

class TestMuteCallbackUC:
    @pytest.mark.asyncio
    async def test_mute_callback_edits_markup(self) -> None:
        """T11: mute button press edits original message markup to unmute buttons.

        Given valid mute callback,
        When MuteCallbackUC is called,
        Then gateway.edit_message_reply_markup called on the source message.
        """
        gateway = AsyncMock()
        state = MuteState()
        repo = AsyncMock()
        uc = MuteCallbackUC(
            _mute_state=state,
            _mute_repo=repo,
            _gateway=gateway,
            _chat_id=_CHAT_ID,
        )
        await uc(
            callback_query_id="cq-1",
            message_id=55,
            fingerprint=_FP,
            duration_str="1h",
            now=_NOW,
        )
        gateway.edit_message_reply_markup.assert_called_once()
        call_kwargs = gateway.edit_message_reply_markup.call_args.kwargs
        assert call_kwargs["message_id"] == 55
        # New markup should contain unmute button
        new_markup = call_kwargs["reply_markup"]
        markup_str = str(new_markup)
        assert "unmute" in markup_str.lower()

    @pytest.mark.asyncio
    async def test_mute_callback_stores_source_message_id(self) -> None:
        """T11: source_message_id is stored in MuteEntry.

        Given mute callback with message_id=55,
        When executed,
        Then state entry has source_message_id=55.
        """
        gateway = AsyncMock()
        state = MuteState()
        repo = AsyncMock()
        uc = MuteCallbackUC(
            _mute_state=state,
            _mute_repo=repo,
            _gateway=gateway,
            _chat_id=_CHAT_ID,
        )
        await uc(
            callback_query_id="cq-1",
            message_id=55,
            fingerprint=_FP,
            duration_str="1h",
            now=_NOW,
        )
        entry = state.get_entry(_FP)
        assert entry is not None
        assert entry.source_message_id == 55


class TestUnmuteCallbackUC:
    @pytest.mark.asyncio
    async def test_unmute_callback_restores_buttons(self) -> None:
        """
        Given an active mute,
        When UnmuteCallbackUC is called,
        Then gateway.edit_message_reply_markup called with original mute buttons.
        """
        gateway = AsyncMock()
        state = MuteState()
        state.mute(fingerprint=_FP, duration_sec=3600, source_message_id=55, now=_NOW)
        repo = AsyncMock()
        uc = UnmuteCallbackUC(
            _mute_state=state,
            _mute_repo=repo,
            _gateway=gateway,
            _chat_id=_CHAT_ID,
        )
        await uc(
            callback_query_id="cq-2",
            message_id=55,
            fingerprint=_FP,
            now=_NOW + 60,
        )
        gateway.edit_message_reply_markup.assert_called_once()
        call_kwargs = gateway.edit_message_reply_markup.call_args.kwargs
        markup_str = str(call_kwargs["reply_markup"])
        assert "mute" in markup_str.lower()
        assert "🔇" in markup_str

    @pytest.mark.asyncio
    async def test_edit_failure_swallowed(self) -> None:
        """T13: failure to edit source message is swallowed (non-fatal).

        Given edit_message_reply_markup raises,
        When UnmuteCallbackUC is called,
        Then no exception propagates.
        """
        gateway = AsyncMock()
        gateway.edit_message_reply_markup = AsyncMock(side_effect=RuntimeError("tg error"))
        state = MuteState()
        state.mute(fingerprint=_FP, duration_sec=3600, source_message_id=55, now=_NOW)
        repo = AsyncMock()
        uc = UnmuteCallbackUC(
            _mute_state=state,
            _mute_repo=repo,
            _gateway=gateway,
            _chat_id=_CHAT_ID,
        )
        # Should not raise
        await uc(
            callback_query_id="cq-3",
            message_id=55,
            fingerprint=_FP,
            now=_NOW + 60,
        )
        # answer_callback_query should still have been called
        gateway.answer_callback_query.assert_called_once()
