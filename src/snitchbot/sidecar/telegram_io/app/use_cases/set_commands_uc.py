"""SetCommandsUC — registers bot commands via setMyCommands.

Called once per sidecar startup (after first successful getUpdates).
Non-fatal on failure.
"""
from dataclasses import dataclass

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway

__all__ = ["SetCommandsUC", "BOT_COMMANDS"]

BOT_COMMANDS = [
    {"command": "status", "description": "Sidecar snapshot: clients, traffic, queue"},
    {"command": "last", "description": "Last N errors with fingerprints"},
    {"command": "test", "description": "Verify delivery channel is working"},
    {"command": "mute", "description": "Mute events by fingerprint or globally"},
    {"command": "unmute", "description": "Remove a mute"},
    {"command": "chart", "description": "ASCII charts of CPU, memory, FDs, threads"},
    {"command": "export", "description": "Export vitals as CSV file"},
]

@dataclass(frozen=True, slots=True, kw_only=True)
class SetCommandsUC:
    """Use case for registering bot commands with Telegram.

    Dependencies:
        _gateway : ITelegramGateway
        _chat_id : str
    """

    _gateway: ITelegramGateway
    _chat_id: str

    async def __call__(self) -> None:
        """Call setMyCommands scoped to the configured chat_id.

        Non-fatal: errors are swallowed (logged by gateway or caller).
        """
        scope = {
            "type": "chat",
            "chat_id": self._chat_id,
        }
        await self._gateway.set_my_commands(
            commands=BOT_COMMANDS,
            scope=scope,
        )
