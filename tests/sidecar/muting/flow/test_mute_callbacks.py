"""Flow tests for MuteCallbackUC and UnmuteCallbackUC.

Extracted from tests/sidecar/flow/interactive/test_callbacks.py.
Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §9, §10.

Invariants validated: T11 (edit source message), T13 (edit failure swallowed).
"""
from unittest.mock import AsyncMock

import pytest

from snitchbot.sidecar.muting.app.use_cases.mute_callback_uc import MuteCallbackUC
from snitchbot.sidecar.muting.app.use_cases.unmute_callback_uc import UnmuteCallbackUC
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

_CHAT_ID = "-100123456"
_NOW = 1_000_000.0
_FP = "a1b2c3"


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


# ---------------------------------------------------------------------------
# UnmuteCallbackUC tests
# ---------------------------------------------------------------------------

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
        gateway.answer_callback_query.assert_called_once()
