"""MuteCallbackUC — handles mute inline-button callback.

callback_data format: "mute:<fingerprint>:<duration>"
"""
import datetime
import logging
import time
from dataclasses import dataclass

from snitchbot.shared.domain.services import fmt_window_label
from snitchbot.shared.domain.services import (
    WindowParseError,
    parse_window_seconds,
)
from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.muting.app.interfaces.i_muting_deps import IMuteRepo
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

logger = logging.getLogger(__name__)
__all__ = ["MuteCallbackUC"]

@dataclass(frozen=True, slots=True, kw_only=True)
class MuteCallbackUC:
    """Use case for mute inline button callback."""

    _mute_state: MuteState
    _mute_repo: IMuteRepo
    _gateway: ITelegramGateway
    _chat_id: str

    async def __call__(
        self,
        *,
        callback_query_id: str,
        message_id: int,
        fingerprint: str,
        duration_str: str,
        exception_type: str | None = None,
        now: float | None = None,
    ) -> None:
        """Handle mute callback.

        1. Parse duration.
        2. Apply mute (store source_message_id).
        3. Edit reply markup to unmute buttons.
        4. Answer callback query.
        """
        if now is None:
            now = time.time()

        try:
            duration_sec = parse_window_seconds(duration_str)
        except WindowParseError:
            await self._gateway.answer_callback_query(
                callback_query_id=callback_query_id,
                text=f"❌ Invalid duration: {duration_str}",
                show_alert=True,
            )
            return

        success = self._mute_state.mute(
            fingerprint=fingerprint,
            duration_sec=duration_sec,
            source_message_id=message_id,
            now=now,
            exception_type=exception_type,
        )

        dur_label = fmt_window_label(duration_sec)

        if not success:  # TODO: override existing mute instead of rejecting
            # Already muted
            await self._gateway.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Already muted",
                show_alert=False,
            )
            return

        # Persist
        try:
            await self._mute_repo.save(self._mute_state)
        except Exception:
            logger.debug("mute callback persist failed", exc_info=True)

        expires_at = now + duration_sec
        exp_str = datetime.datetime.fromtimestamp(
            expires_at, tz=datetime.timezone.utc,
        ).strftime("%H:%M UTC")

        # Edit original message markup -> unmute buttons
        unmute_markup = {
            "inline_keyboard": [[
                {"text": "🔔 unmute", "callback_data": f"unmute:{fingerprint}"},
                {"text": "📋 trace", "callback_data": f"trace:{fingerprint}"},
            ]]
        }
        try:
            await self._gateway.edit_message_reply_markup(
                chat_id=self._chat_id,
                message_id=message_id,
                reply_markup=unmute_markup,
            )
        except Exception:
            logger.debug("mute callback edit markup failed", exc_info=True)

        # Answer callback query
        await self._gateway.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Muted for {dur_label} (until {exp_str})",
            show_alert=False,
        )

