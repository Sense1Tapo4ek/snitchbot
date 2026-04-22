"""UnmuteCallbackUC — handles unmute inline-button callback.

callback_data format: "unmute:<fingerprint>"
"""
import logging
import time
from dataclasses import dataclass

from snitchbot.shared.domain.services import fmt_window_label
from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.muting.app.interfaces.i_muting_deps import IMuteRepo
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

logger = logging.getLogger(__name__)
__all__ = ["UnmuteCallbackUC"]

@dataclass(frozen=True, slots=True, kw_only=True)
class UnmuteCallbackUC:
    """Use case for unmute inline button callback."""

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
        now: float | None = None,
    ) -> None:
        """Handle unmute callback.

        1. Remove mute.
        2. Edit reply markup back to original mute buttons.
        3. Answer callback query.
        """
        if now is None:
            now = time.time()

        lookup_fp = fingerprint if fingerprint != "all" else None
        entry = self._mute_state.get_entry(lookup_fp)
        remaining_sec = max(0.0, entry.expires_at - now) if entry else 0.0

        success = self._mute_state.unmute(fingerprint=fingerprint if fingerprint != "all" else None)

        if not success:
            await self._gateway.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Not muted",
                show_alert=False,
            )
            return

        # Persist
        try:
            await self._mute_repo.save(self._mute_state)
        except Exception:
            logger.debug("unmute callback persist failed", exc_info=True)

        remaining_label = (
            fmt_window_label(remaining_sec) if remaining_sec >= 60
            else f"{int(remaining_sec)}s"
        )

        # Restore original mute buttons
        fp = fingerprint
        original_markup = {
            "inline_keyboard": [[
                {"text": "🔇 5m", "callback_data": f"mute:{fp}:5m"},
                {"text": "🔇 1h", "callback_data": f"mute:{fp}:1h"},
                {"text": "🔇 24h", "callback_data": f"mute:{fp}:24h"},
                {"text": "📋 trace", "callback_data": f"trace:{fp}"},
            ]]
        }
        try:
            await self._gateway.edit_message_reply_markup(
                chat_id=self._chat_id,
                message_id=message_id,
                reply_markup=original_markup,
            )
        except Exception:
            logger.debug("unmute callback edit markup failed", exc_info=True)

        await self._gateway.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Unmuted ({remaining_label} remaining cancelled)",
            show_alert=False,
        )

