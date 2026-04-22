"""ResolveTopicUseCase - service -> message_thread_id (Invariants F3, F4, F6).

Layer: app/use_cases. Dependencies are Protocol-typed.

F3: cache-first lookup; only create when missing.
F4: per-service asyncio.Lock serializes concurrent creates for the same service.
F6: missing can_manage_topics permission => return None; caller routes to General.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from snitchbot.sidecar.telegram_io.app.interfaces.i_topic_store import ITopicStore
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import TgPermissionError


class _ITgTopicGateway(Protocol):
    async def create_forum_topic(
        self, *, chat_id: str, name: str, icon_color: int,
    ) -> int: ...


@dataclass(slots=True, kw_only=True)
class ResolveTopicUseCase:
    _registry: TopicRegistry
    _store: ITopicStore
    _gateway: _ITgTopicGateway
    _chat_id: str
    _now: Callable[[], float]
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def __call__(self, *, service: str, icon_color: int) -> int | None:
        cached = self._registry.lookup(service)
        if cached is not None:
            return cached.message_thread_id

        lock = self._locks.setdefault(service, asyncio.Lock())
        async with lock:
            # double-check after acquiring lock (F4)
            cached = self._registry.lookup(service)
            if cached is not None:
                return cached.message_thread_id

            try:
                thread_id = await self._gateway.create_forum_topic(
                    chat_id=self._chat_id, name=service, icon_color=icon_color,
                )
            except TgPermissionError:
                return None  # F6: caller routes to General topic

            mapping = TopicMappingVO(
                service=service,
                message_thread_id=thread_id,
                created_at=self._now(),
            )
            self._registry.register(mapping)
            self._store.save(list(self._registry.snapshot()))
            return thread_id

    def invalidate(self, service: str) -> None:
        """F5 helper: drop a stale mapping after `message thread not found`."""
        self._registry.forget(service)
        self._store.save(list(self._registry.snapshot()))
