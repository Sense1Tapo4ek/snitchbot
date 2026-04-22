"""CommandRouter — dispatches Telegram slash commands to use cases.

Receives a parsed Telegram message dict, extracts command + args, calls the
appropriate UC, and sends the reply via the gateway.
"""
import logging
from dataclasses import dataclass

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.telegram_io.app.interfaces.i_command_handlers import (
    ICommandBudget,
    ICommandHandler,
    ITestHandler,
)

__all__ = ["CommandRouter"]

logger = logging.getLogger("snitchbot.sidecar.command_router")

_COMMANDS = frozenset({"status", "last", "test", "mute", "unmute", "chart", "export"})

@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRouter:
    """Routes incoming Telegram commands to the correct use case.

    Dependencies:
        _status_query   : StatusQuery
        _last_query     : LastQuery
        _test_uc        : TestUC
        _mute_uc        : MuteUC
        _unmute_uc      : UnmuteUC
        _gateway        : ITelegramGateway
        _chat_id        : str
        _command_budget : CommandBudget
    """

    _status_query: ICommandHandler
    _last_query: ICommandHandler
    _test_uc: ITestHandler
    _mute_uc: ICommandHandler
    _unmute_uc: ICommandHandler
    _chart_query: ICommandHandler
    _export_query: ICommandHandler
    _gateway: ITelegramGateway
    _chat_id: str
    _command_budget: ICommandBudget

    async def handle(self, message: dict) -> None:
        """Dispatch a message to the correct command UC.

        Args:
            message: Telegram message dict from getUpdates.
        """
        text: str = message.get("text", "") or ""
        if not text.startswith("/"):
            return

        # Parse command and args
        parts = text.lstrip("/").split(None, 1)
        raw_cmd = parts[0].split("@")[0].lower()  # strip bot username suffix
        args = parts[1] if len(parts) > 1 else ""

        if raw_cmd not in _COMMANDS:
            logger.debug("command_router: unknown command %r, ignoring", raw_cmd)
            return

        message_id: int | None = message.get("message_id")
        # Topic id on forum chats; None in private/group chats or outside forum mode.
        message_thread_id: int | None = message.get("message_thread_id")

        # Check command budget BEFORE dispatching
        if not self._command_budget.acquire():
            rate_msg = self._command_budget.rate_limited_message(raw_cmd)
            await self._gateway.send_message(
                chat_id=self._chat_id,
                text=rate_msg,
                parse_mode="HTML",
            )
            return

        try:
            if raw_cmd == "status":
                reply = await self._status_query(args=args, message_thread_id=message_thread_id)
            elif raw_cmd == "last":
                reply = await self._last_query(args=args, message_thread_id=message_thread_id)
            elif raw_cmd == "test":
                reply = await self._test_uc(
                    message_id=message_id, message_thread_id=message_thread_id
                )
            elif raw_cmd == "mute":
                reply = await self._mute_uc(args=args, message_thread_id=message_thread_id)
            elif raw_cmd == "unmute":
                reply = await self._unmute_uc(args=args, message_thread_id=message_thread_id)
            elif raw_cmd == "chart":
                reply = await self._chart_query(args=args, message_thread_id=message_thread_id)
            elif raw_cmd == "export":
                reply = await self._export_query(args=args, message_thread_id=message_thread_id)
            else:
                return

            await self._gateway.send_message(
                chat_id=self._chat_id,
                text=reply.get("text", ""),
                parse_mode=reply.get("parse_mode", "HTML"),
                reply_markup=reply.get("reply_markup"),
                reply_to_message_id=reply.get("reply_to_message_id"),
            )
        except Exception:
            logger.exception("command_router: error handling command %r", raw_cmd)
