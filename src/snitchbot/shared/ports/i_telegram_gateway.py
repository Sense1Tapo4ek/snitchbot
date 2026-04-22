"""Canonical ITelegramGateway Protocol — shared across all bounded contexts.

Single source of truth. Each context imports this instead of defining
its own narrow copy.
"""
from typing import Protocol

__all__ = ["ITelegramGateway"]


class ITelegramGateway(Protocol):
    """Telegram Bot API surface used by the sidecar."""

    async def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
    ) -> int:
        """Send a message. Returns Telegram message_id."""
        ...

    async def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> None: ...

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: int,
        reply_markup: dict,
    ) -> None: ...

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> None: ...

    async def set_my_commands(
        self,
        *,
        commands: list[dict],
        scope: dict | None = None,
    ) -> None: ...

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 60,
    ) -> list[dict]: ...

    async def send_document(
        self,
        *,
        chat_id: str,
        document: bytes,
        filename: str,
        caption: str | None = None,
    ) -> int:
        """Send a file as document. Returns Telegram message_id."""
        ...

    async def close(self) -> None: ...
