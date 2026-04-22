"""TelegramIOFacade — thin driving port exposing Telegram I/O to other contexts.

Delegates verbatim to TgGatewayHttpx + SetCommandsUC.
Business logic lives in the gateway and use cases, not here.
"""
from dataclasses import dataclass, field
from typing import Any

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.telegram_io.app.use_cases.resolve_topic_uc import (
    ResolveTopicUseCase,
)
from snitchbot.sidecar.telegram_io.app.use_cases.set_commands_uc import SetCommandsUC
from snitchbot.sidecar.telegram_io.domain.forum_mode_vo import ForumModeVO
from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TopicColorService,
)
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)

__all__ = ["TelegramIOFacade"]


def _default_forum_mode() -> ForumModeVO:
    return ForumModeVO(is_forum=False, can_manage_topics=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramIOFacade:
    """Public API of the telegram_io bounded context.

    Other contexts use this facade; they never import gateway or UCs directly.
    """

    _gateway: ITelegramGateway
    _set_commands_uc: SetCommandsUC
    _forum_mode: ForumModeVO = field(default_factory=_default_forum_mode)
    _registry: TopicRegistry = field(default_factory=TopicRegistry)
    _resolve_topic_uc: ResolveTopicUseCase | None = None
    _color_overrides: dict[str, int] = field(default_factory=dict)

    @property
    def forum_mode(self) -> ForumModeVO:
        return self._forum_mode

    async def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> int:
        return await self._gateway.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )

    async def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        await self._gateway.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: int,
        reply_markup: dict[str, Any],
    ) -> None:
        await self._gateway.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> None:
        await self._gateway.answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 60,
    ) -> list[dict[str, Any]]:
        return await self._gateway.get_updates(offset=offset, timeout=timeout)

    async def set_commands(self) -> None:
        await self._set_commands_uc()

    async def resolve_topic(self, *, service: str) -> int | None:
        """Forum mode: return message_thread_id (creates on cache miss).

        Returns None when degraded (no topic rights) — caller falls back to General.
        Returns None unconditionally in simple mode.
        """
        if not self._forum_mode.fully_capable:
            return None
        if self._resolve_topic_uc is None:
            return None
        color = TopicColorService.color_for(
            service, override=self._color_overrides.get(service),
        )
        return await self._resolve_topic_uc(service=service, icon_color=color)

    def reverse_lookup(self, message_thread_id: int) -> str | None:
        """Forum mode: return service name bound to a thread id, or None."""
        return self._registry.reverse_lookup(message_thread_id)

    def invalidate_topic(self, service: str) -> None:
        """Drop a stale mapping after `message thread not found` (F5)."""
        if self._resolve_topic_uc is None:
            return
        self._resolve_topic_uc.invalidate(service)

    async def close(self) -> None:
        await self._gateway.close()
