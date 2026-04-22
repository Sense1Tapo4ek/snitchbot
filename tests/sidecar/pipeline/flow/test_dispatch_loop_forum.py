"""Flow tests for DispatchLoopWorkflow — forum-mode per-service topic routing.

Spec: forum-mode plan F-T11, Invariant F5 (stale thread_id -> invalidate + retry).

Uses AsyncMock for all collaborators (gateway, queue, rate bucket, dedup cache,
telegram_io facade).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.pipeline.app.workflows.dispatch_loop_workflow import (
    DispatchLoopWorkflow,
)
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import (
    TgThreadNotFoundError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_queue_item(
    *,
    priority: QueuePriority = QueuePriority.NEW_ALERT,
    fingerprint: str = "fp-abc",
    action: str = "new_alert",
    service: str | None = "svc-a",
) -> QueueItem:
    payload: dict = {
        "fingerprint": fingerprint,
        "action": action,
        "msg": "boom",
    }
    if service is not None:
        payload["service"] = service
    return QueueItem(priority=priority, payload=payload)


def _make_facade(
    *,
    resolve_return: int | None = None,
    resolve_side_effect: object = None,
) -> MagicMock:
    """Forum-mode facade mock. resolve_topic is AsyncMock, invalidate_topic MagicMock."""
    facade = MagicMock()
    if resolve_side_effect is not None:
        facade.resolve_topic = AsyncMock(side_effect=resolve_side_effect)
    else:
        facade.resolve_topic = AsyncMock(return_value=resolve_return)
    facade.invalidate_topic = MagicMock()
    return facade


def _make_workflow(
    *,
    queue: MagicMock,
    gateway: AsyncMock,
    telegram_io: MagicMock,
    rate_bucket: MagicMock | None = None,
    dedup_cache: MagicMock | None = None,
    render_fn: MagicMock | None = None,
    chat_id: str = "-100123456",
) -> DispatchLoopWorkflow:
    if rate_bucket is None:
        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True
    if dedup_cache is None:
        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None
    if render_fn is None:
        render_fn = MagicMock(return_value="<b>alert</b>")
    return DispatchLoopWorkflow(
        _queue=queue,
        _rate_bucket=rate_bucket,
        _dedup_cache=dedup_cache,
        _render_fn=render_fn,
        _gateway=gateway,
        _chat_id=chat_id,
        _telegram_io=telegram_io,
    )


# ---------------------------------------------------------------------------
# test_event_with_resolved_thread_id_is_sent_with_message_thread_id
# ---------------------------------------------------------------------------


class TestEventResolvedThreadIdSent:
    @pytest.mark.asyncio
    async def test_send_uses_resolved_thread_id(self) -> None:
        """
        Given facade.resolve_topic(service='svc-a') returns 42,
        When tick() dispatches a queued event for svc-a,
        Then gateway.send_message is called with message_thread_id=42.
        """
        # Arrange
        item = _make_queue_item(service="svc-a")
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 1234

        facade = _make_facade(resolve_return=42)

        workflow = _make_workflow(queue=queue, gateway=gateway, telegram_io=facade)

        # Act
        await workflow.tick()

        # Assert
        facade.resolve_topic.assert_awaited_once_with(service="svc-a")
        gateway.send_message.assert_awaited_once()
        call_kwargs = gateway.send_message.await_args.kwargs
        assert call_kwargs["message_thread_id"] == 42


# ---------------------------------------------------------------------------
# test_resolve_returning_none_falls_back_to_general
# ---------------------------------------------------------------------------


class TestResolveReturningNoneFallsBackToGeneral:
    @pytest.mark.asyncio
    async def test_send_uses_none_thread_id_when_resolver_returns_none(self) -> None:
        """
        Given facade.resolve_topic returns None (simple mode / degraded),
        When tick() dispatches a queued event,
        Then gateway.send_message is called with message_thread_id=None
        (falls back to General).
        """
        # Arrange
        item = _make_queue_item(service="svc-a")
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 7

        facade = _make_facade(resolve_return=None)

        workflow = _make_workflow(queue=queue, gateway=gateway, telegram_io=facade)

        # Act
        await workflow.tick()

        # Assert
        facade.resolve_topic.assert_awaited_once_with(service="svc-a")
        gateway.send_message.assert_awaited_once()
        call_kwargs = gateway.send_message.await_args.kwargs
        assert call_kwargs["message_thread_id"] is None
        facade.invalidate_topic.assert_not_called()


# ---------------------------------------------------------------------------
# test_thread_not_found_invalidates_and_retries_once (F5)
# ---------------------------------------------------------------------------


class TestThreadNotFoundInvalidatesAndRetriesOnce:
    @pytest.mark.asyncio
    async def test_stale_thread_is_invalidated_and_retried_once(self) -> None:
        """
        Given gateway.send_message raises TgThreadNotFoundError on first call
        then returns 5678 on the second call,
        And facade.resolve_topic yields [42, 99] in order,
        When tick() dispatches an event,
        Then invalidate_topic is called once with the service,
        gateway.send_message is called twice with thread_ids [42, 99] in order,
        and no exception propagates.

        Invariant F5: stale thread_id -> invalidate + re-resolve + retry once.
        """
        # Arrange
        item = _make_queue_item(service="svc-a")
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.side_effect = [
            TgThreadNotFoundError(),
            5678,
        ]

        facade = _make_facade(resolve_side_effect=[42, 99])

        workflow = _make_workflow(queue=queue, gateway=gateway, telegram_io=facade)

        # Act
        await workflow.tick()

        # Assert: invalidate called once with the service
        facade.invalidate_topic.assert_called_once_with("svc-a")

        # resolve_topic called twice (initial + re-resolve after invalidate)
        assert facade.resolve_topic.await_count == 2
        facade.resolve_topic.assert_any_await(service="svc-a")

        # send_message called twice, with thread_ids 42 then 99 in order
        assert gateway.send_message.await_count == 2
        sent_thread_ids = [
            c.kwargs["message_thread_id"]
            for c in gateway.send_message.await_args_list
        ]
        assert sent_thread_ids == [42, 99]


# ---------------------------------------------------------------------------
# test_thread_not_found_twice_in_row_drops_event
# ---------------------------------------------------------------------------


class TestThreadNotFoundTwiceDropsEvent:
    @pytest.mark.asyncio
    async def test_second_thread_not_found_bubbles_up(self) -> None:
        """
        Given gateway.send_message raises TgThreadNotFoundError on BOTH attempts,
        When tick() dispatches an event,
        Then invalidate_topic is called once, send_message is attempted twice,
        and the second TgThreadNotFoundError propagates to the caller so the
        outer supervisor can decide how to react (match existing behaviour for
        TgRateLimitError: the workflow does not silently swallow gateway
        exceptions).
        """
        # Arrange
        item = _make_queue_item(service="svc-b")
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.side_effect = [
            TgThreadNotFoundError(),
            TgThreadNotFoundError(),
        ]

        facade = _make_facade(resolve_side_effect=[100, 200])

        workflow = _make_workflow(queue=queue, gateway=gateway, telegram_io=facade)

        # Act & Assert: second attempt's exception bubbles up
        with pytest.raises(TgThreadNotFoundError):
            await workflow.tick()

        # invalidate_topic was called once (only after the first failure)
        facade.invalidate_topic.assert_called_once_with("svc-b")

        # send_message attempted exactly twice (original + one retry)
        assert gateway.send_message.await_count == 2
