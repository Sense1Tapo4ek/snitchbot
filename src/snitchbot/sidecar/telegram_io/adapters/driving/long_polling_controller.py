"""LongPollingController — async getUpdates loop for the Telegram bot.

Architecture:
- Single asyncio coroutine: poll -> route -> repeat.
- chat_id filter: messages from other chats are silently ignored (T1).
- Error handling: backoff 1->2->4->8->30s capped (§2.7, T2).
- Dispatch loop is NOT affected by polling errors.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.telegram_io.app.interfaces.i_command_handlers import (
    ICallbackRouter,
    ICommandRouter,
    ISidecarSession,
    SetCommandsFn,
)

__all__ = ["LongPollingController"]

logger = logging.getLogger("snitchbot.sidecar.long_polling")

_BACKOFF_SEQUENCE = [1, 2, 4, 8, 30]

@dataclass
class LongPollingController:
    """Async long-polling loop.

    Not frozen: needs mutable _running, _offset, stats.

    Dependencies:
        _gateway        : ITelegramGateway
        _command_router : CommandRouter
        _callback_router: CallbackRouter
        _chat_id        : str
        _session        : SidecarSession  (for setMyCommands trigger)
        _stats          : dict  (sidecar stats)
        _set_commands_fn: callable | None  (async, called once on first hello)
    """

    _gateway: ITelegramGateway
    _command_router: ICommandRouter
    _callback_router: ICallbackRouter
    _chat_id: str
    _session: ISidecarSession
    _stats: dict[str, int]
    _set_commands_fn: SetCommandsFn | None = field(default=None)

    _running: bool = field(default=False, init=False)
    _offset: int | None = field(default=None, init=False)

    async def run(self) -> None:
        """Main long-polling loop. Runs until stop() is called."""
        self._running = True
        backoff_idx = 0

        while self._running:
            try:
                updates = await self._gateway.get_updates(
                    offset=self._offset,
                    timeout=60,
                )
                backoff_idx = 0  # reset on success

                for update in updates:
                    update_id: int = update.get("update_id", 0)
                    self._offset = update_id + 1

                    await self._route_update(update)

            except asyncio.CancelledError:
                break
            except Exception:
                self._stats["long_polling_errors"] = (
                    self._stats.get("long_polling_errors", 0) + 1
                )
                delay = _BACKOFF_SEQUENCE[min(backoff_idx, len(_BACKOFF_SEQUENCE) - 1)]
                backoff_idx = min(backoff_idx + 1, len(_BACKOFF_SEQUENCE) - 1)
                logger.warning(
                    "long_polling: error, backing off %ds (error #%d)",
                    delay,
                    self._stats["long_polling_errors"],
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break

    async def _route_update(self, update: dict) -> None:
        """Route a single update to command or callback router."""
        if "message" in update:
            msg = update["message"]
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != self._chat_id:
                # T1: silently ignore messages from other chats
                return
            await self._command_router.handle(msg)

        elif "callback_query" in update:
            cq = update["callback_query"]
            await self._callback_router.handle(cq)

    def stop(self) -> None:
        """Signal the loop to stop."""
        self._running = False
