"""Central dispatch loop workflow.

"""
import logging
from collections.abc import Callable
from dataclasses import dataclass

from snitchbot.shared.generics.errors import TgRateLimitError
from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.pipeline.domain.central_queue_agg import CentralQueue, QueuePriority
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.sidecar.pipeline.domain.services.button_builder_service import build_buttons
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import TgThreadNotFoundError
from snitchbot.sidecar.telegram_io.ports.driving.telegram_io_facade import (
    TelegramIOFacade,
)

logger = logging.getLogger("snitchbot.sidecar.dispatch")

__all__ = ["DispatchLoopWorkflow"]

@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchLoopWorkflow:
    """Main dispatch pipeline: queue -> rate-limit -> send/edit -> store message_id.

    Called as a periodic tick from the sidecar event loop.
    """

    _queue: CentralQueue
    _rate_bucket: RateBucket
    _dedup_cache: DedupCache
    _render_fn: Callable
    _gateway: ITelegramGateway
    _chat_id: str
    _telegram_io: TelegramIOFacade

    async def tick(self) -> None:
        """Process one item from the queue.

        Steps:
        1. Dequeue. If empty, return immediately.
        2. Consult rate bucket (RL1 / RL2 critical bypass).
           - Non-critical: acquire from main bucket; if denied, requeue and return.
           - Critical: acquire from ceiling policy; if denied, drop (no requeue).
        3. Determine send vs edit path:
           - action=counter_edit + existing entry with message_id -> edit_message_text.
           - Otherwise -> send_message.
        4. On successful send, store returned message_id in dedup entry.
        5. On TgRateLimitError (RL6): requeue item, re-raise for caller to backoff.
        """
        item = self._queue.dequeue()
        if item is None:
            return

        logger.debug(
            "dispatch: dequeued kind=%s action=%s fp=%s",
            item.payload.get("kind"), item.payload.get("action"),
            str(item.payload.get("fingerprint", ""))[:8],
        )

        is_critical = item.priority == QueuePriority.CRITICAL

        if not self._rate_bucket.acquire(is_critical=is_critical):
            # Non-critical denied -> requeue for later attempt.
            # Critical denied (ceiling hit) -> drop; never requeue critical.
            if not is_critical:
                self._queue.enqueue(item)
            logger.debug("dispatch: rate-limited, critical=%s", is_critical)
            return

        fp = item.payload.get("fingerprint")
        action = item.payload.get("action", "new_alert")

        if action == "counter_edit" and fp:
            entry = self._dedup_cache.get_entry(fp)
            if entry is not None and entry.message_id is not None:
                html = self._render_fn(event=item.payload, dedup_entry=entry)
                await self._gateway.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=entry.message_id,
                    text=html,
                    parse_mode="HTML",
                )
                return

        # New message path (new_alert, severity_upgrade, lifecycle_bypass,
        # or counter_edit without a known message_id yet).
        # Look up dedup entry so render has count/first_seen/last_seen/severity
        entry = self._dedup_cache.get_entry(fp) if fp else None
        html = self._render_fn(event=item.payload, dedup_entry=entry)
        logger.debug("dispatch: rendered %d chars for kind=%s", len(html), item.payload.get("kind"))

        # Build inline keyboard for non-lifecycle events
        reply_markup = None
        kind = item.payload.get("kind", "")
        if fp and kind != "lifecycle":
            payload = item.payload.get("payload") or {}
            has_trace = kind == "crash" or kind == "watchdog" or bool(payload.get("stack"))
            buttons = build_buttons(fingerprint=fp, has_trace=has_trace)
            reply_markup = {"inline_keyboard": buttons}

        service = item.payload.get("service") or "unknown"
        thread_id = await self._telegram_io.resolve_topic(service=service)

        try:
            try:
                msg_id = await self._gateway.send_message(
                    chat_id=self._chat_id,
                    text=html,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    message_thread_id=thread_id,
                )
            except TgThreadNotFoundError:
                # F5: stale thread_id — invalidate cache, re-resolve, retry once.
                logger.warning(
                    "dispatch: thread not found for service=%s thread_id=%s; "
                    "invalidating and retrying",
                    service, thread_id,
                )
                self._telegram_io.invalidate_topic(service)
                thread_id = await self._telegram_io.resolve_topic(service=service)
                msg_id = await self._gateway.send_message(
                    chat_id=self._chat_id,
                    text=html,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    message_thread_id=thread_id,
                )
            logger.debug("dispatch: sent msg_id=%s", msg_id)
            if fp:
                entry = self._dedup_cache.get_entry(fp)
                if entry is not None:
                    entry.message_id = msg_id
        except TgRateLimitError:
            logger.debug("dispatch: rate-limited by Telegram, requeuing")
            self._queue.enqueue(item)
            raise
