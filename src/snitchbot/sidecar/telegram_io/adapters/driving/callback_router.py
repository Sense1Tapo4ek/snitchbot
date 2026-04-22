"""CallbackRouter — parses and dispatches inline-button callback queries.

callback_data formats:
  mute:<fp>:<duration>      -> MuteCallbackUC
  unmute:<fp>               -> UnmuteCallbackUC
  trace:<fp>                -> TraceCallbackUC
"""
import logging
from dataclasses import dataclass

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.telegram_io.app.interfaces.i_command_handlers import (
    IMuteCallbackHandler,
    ITraceCallbackHandler,
    IUnmuteCallbackHandler,
)

__all__ = ["CallbackRouter", "CallbackParseError"]

logger = logging.getLogger("snitchbot.sidecar.callback_router")

class CallbackParseError(ValueError):
    """Raised when callback_data cannot be parsed."""

def parse_callback_data(data: str) -> tuple[str, ...]:
    """Parse callback_data into (action, *parts).

    Returns:
        ("mute", fp, duration) | ("unmute", fp) | ("trace", fp)

    Raises:
        CallbackParseError on unrecognized format.
    """
    parts = data.split(":")
    action = parts[0]

    if action == "mute":
        if len(parts) != 3:
            raise CallbackParseError(f"mute callback expects 3 parts, got {len(parts)}: {data!r}")
        return ("mute", parts[1], parts[2])

    if action == "unmute":
        if len(parts) != 2:
            raise CallbackParseError(f"unmute callback expects 2 parts, got {len(parts)}: {data!r}")
        return ("unmute", parts[1])

    if action == "trace":
        if len(parts) != 2:
            raise CallbackParseError(f"trace callback expects 2 parts, got {len(parts)}: {data!r}")
        return ("trace", parts[1])

    raise CallbackParseError(f"Unknown callback action {action!r}: {data!r}")

@dataclass(frozen=True, slots=True, kw_only=True)
class CallbackRouter:
    """Routes inline-button callbacks to the correct use case.

    Dependencies:
        _mute_cb_uc     : MuteCallbackUC
        _unmute_cb_uc   : UnmuteCallbackUC
        _trace_cb_uc    : TraceCallbackUC
        _gateway        : ITelegramGateway
        _chat_id        : str
    """

    _mute_cb_uc: IMuteCallbackHandler
    _unmute_cb_uc: IUnmuteCallbackHandler
    _trace_cb_uc: ITraceCallbackHandler
    _gateway: ITelegramGateway
    _chat_id: str

    async def handle(self, callback_query: dict) -> None:
        """Dispatch a callback_query to the correct use case.

        answerCallbackQuery does NOT consume the main rate bucket (RL8).

        Args:
            callback_query: Telegram callback_query dict from getUpdates.
        """
        cq_id: str = callback_query.get("id", "")
        data: str = callback_query.get("data", "")
        message: dict = callback_query.get("message", {})
        message_id: int = message.get("message_id", 0)
        chat_id: str = str(message.get("chat", {}).get("id", ""))

        # Validate chat_id — T1 variant for callbacks
        if chat_id != self._chat_id:
            logger.debug("callback_router: callback from foreign chat %r, ignoring", chat_id)
            return

        try:
            parsed = parse_callback_data(data)
        except CallbackParseError as exc:
            logger.warning("callback_router: parse error: %s", exc)
            # Answer with error — T12
            try:
                await self._gateway.answer_callback_query(
                    callback_query_id=cq_id,
                    text=f"❌ Invalid button data: {data[:30]}",
                    show_alert=True,
                )
            except Exception:
                logger.debug("callback: answer_callback_query failed", exc_info=True)
            return

        action = parsed[0]
        try:
            if action == "mute":
                _, fp, dur = parsed
                await self._mute_cb_uc(
                    callback_query_id=cq_id,
                    message_id=message_id,
                    fingerprint=fp,
                    duration_str=dur,
                )
            elif action == "unmute":
                _, fp = parsed
                await self._unmute_cb_uc(
                    callback_query_id=cq_id,
                    message_id=message_id,
                    fingerprint=fp,
                )
            elif action == "trace":
                _, fp = parsed
                await self._trace_cb_uc(
                    callback_query_id=cq_id,
                    fingerprint=fp,
                )
        except Exception:
            logger.exception("callback_router: error handling callback action %r", action)
