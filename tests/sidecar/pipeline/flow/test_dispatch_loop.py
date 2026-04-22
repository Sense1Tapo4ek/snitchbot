"""Flow tests for DispatchLoopWorkflow — central dispatch pipeline.

Spec: docs/superpowers/specs/2026-04-11-dedup-rate-limit-design.md §4.7, §4.8.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 8.2.

Invariants validated: RL2, RL6.

Uses AsyncMock for all collaborators (gateway, queue, rate bucket, dedup cache).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.pipeline.app.workflows.dispatch_loop_workflow import DispatchLoopWorkflow
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache, DedupEntry
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.shared.generics.errors import TgRateLimitError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queue_item(
    priority: QueuePriority = QueuePriority.NEW_ALERT,
    fingerprint: str = "fp-abc",
    action: str = "new_alert",
) -> QueueItem:
    return QueueItem(
        priority=priority,
        payload={"fingerprint": fingerprint, "action": action, "msg": "boom"},
    )


def _make_facade() -> MagicMock:
    """Build a simple-mode TelegramIOFacade mock.

    resolve_topic returns None (simple mode) and invalidate_topic is a no-op.
    """
    facade = MagicMock()
    facade.resolve_topic = AsyncMock(return_value=None)
    facade.invalidate_topic = MagicMock()
    return facade


def _make_workflow(
    *,
    queue: MagicMock | None = None,
    rate_bucket: MagicMock | None = None,
    dedup_cache: MagicMock | None = None,
    render_fn: MagicMock | None = None,
    gateway: AsyncMock | None = None,
    chat_id: str = "-100123456",
    telegram_io: MagicMock | None = None,
) -> DispatchLoopWorkflow:
    return DispatchLoopWorkflow(
        _queue=queue if queue is not None else MagicMock(spec=CentralQueue),
        _rate_bucket=rate_bucket if rate_bucket is not None else MagicMock(spec=RateBucket),
        _dedup_cache=dedup_cache if dedup_cache is not None else MagicMock(spec=DedupCache),
        _render_fn=render_fn if render_fn is not None else MagicMock(return_value="<b>alert</b>"),
        _gateway=gateway if gateway is not None else AsyncMock(spec=ITelegramGateway),
        _chat_id=chat_id,
        _telegram_io=telegram_io if telegram_io is not None else _make_facade(),
    )


# ---------------------------------------------------------------------------
# test_dispatch_drains_queue
# ---------------------------------------------------------------------------


class TestDispatchDrainsQueue:
    @pytest.mark.asyncio
    async def test_dequeue_called_and_send_message_called(self) -> None:
        """
        Given a queue with one item,
        When tick() is called,
        Then dequeue() is called once and gateway.send_message() is called once.
        """
        # Arrange
        item = _make_queue_item()
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 42

        render_fn = MagicMock(return_value="<b>alert</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        await workflow.tick()

        # Assert
        queue.dequeue.assert_called_once()
        gateway.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_returns_immediately_when_queue_empty(self) -> None:
        """
        Given an empty queue,
        When tick() is called,
        Then dequeue is called but send_message is never called.
        """
        # Arrange
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = None
        gateway = AsyncMock(spec=ITelegramGateway)

        workflow = _make_workflow(queue=queue, gateway=gateway)

        # Act
        await workflow.tick()

        # Assert
        queue.dequeue.assert_called_once()
        gateway.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# test_dispatch_consults_rate_bucket
# ---------------------------------------------------------------------------


class TestDispatchConsultsRateBucket:
    @pytest.mark.asyncio
    async def test_acquire_called_before_send(self) -> None:
        """
        Given a queue item and a full rate bucket,
        When tick() is called,
        Then rate_bucket.acquire() is called before gateway.send_message().
        """
        # Arrange
        call_order: list[str] = []

        item = _make_queue_item()
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)

        def acquire_side_effect(**kwargs):
            call_order.append("acquire")
            return True

        rate_bucket.acquire.side_effect = acquire_side_effect

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None

        gateway = AsyncMock(spec=ITelegramGateway)

        async def send_side_effect(**kwargs):
            call_order.append("send")
            return 99

        gateway.send_message.side_effect = send_side_effect

        render_fn = MagicMock(return_value="<b>x</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        await workflow.tick()

        # Assert
        assert call_order == ["acquire", "send"]


# ---------------------------------------------------------------------------
# test_dispatch_skips_when_bucket_empty_requeues
# ---------------------------------------------------------------------------


class TestDispatchSkipsWhenBucketEmptyRequeues:
    @pytest.mark.asyncio
    async def test_item_requeued_when_acquire_returns_false(self) -> None:
        """
        Given a non-critical queue item and an empty rate bucket (acquire=False),
        When tick() is called,
        Then the item is re-enqueued and send_message is never called.
        """
        # Arrange
        item = _make_queue_item(priority=QueuePriority.NEW_ALERT)
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = False

        gateway = AsyncMock(spec=ITelegramGateway)

        workflow = _make_workflow(queue=queue, rate_bucket=rate_bucket, gateway=gateway)

        # Act
        await workflow.tick()

        # Assert: item requeued
        queue.enqueue.assert_called_once_with(item)
        gateway.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# test_dispatch_critical_bypasses_bucket — RL2
# ---------------------------------------------------------------------------


class TestDispatchCriticalBypassesBucket:
    @pytest.mark.asyncio
    async def test_critical_item_acquire_called_with_is_critical_true(self) -> None:
        """
        Given a CRITICAL priority queue item,
        When tick() is called,
        Then rate_bucket.acquire(is_critical=True) is called.

        RL2: critical events bypass main bucket, subject to ceiling check.
        """
        # Arrange
        item = _make_queue_item(priority=QueuePriority.CRITICAL)
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 1

        render_fn = MagicMock(return_value="<b>critical</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        await workflow.tick()

        # Assert: acquire called with is_critical=True
        rate_bucket.acquire.assert_called_once_with(is_critical=True)

    @pytest.mark.asyncio
    async def test_critical_item_not_requeued_when_bucket_full(self) -> None:
        """
        Given a CRITICAL priority queue item and acquire returns False (ceiling hit),
        When tick() is called,
        Then the critical item is NOT requeued (RL2: never dropped to requeue loop,
        ceiling rejection is final — critical bypass ceiling just means drop, not requeue).
        """
        # Arrange
        item = _make_queue_item(priority=QueuePriority.CRITICAL)
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = False  # ceiling hit

        gateway = AsyncMock(spec=ITelegramGateway)

        workflow = _make_workflow(queue=queue, rate_bucket=rate_bucket, gateway=gateway)

        # Act
        await workflow.tick()

        # Assert: NOT requeued (critical doesn't go back to requeue loop)
        queue.enqueue.assert_not_called()
        gateway.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# test_dispatch_handles_429_requeues — RL6
# ---------------------------------------------------------------------------


class TestDispatchHandles429Requeues:
    @pytest.mark.asyncio
    async def test_tg_rate_limit_error_causes_requeue(self) -> None:
        """
        Given a queue item and gateway raises TgRateLimitError on send_message,
        When tick() is called,
        Then the item is re-enqueued and TgRateLimitError is re-raised.

        RL6: 429 from TG -> pause drain, requeue item, graceful resumption.
        """
        # Arrange
        item = _make_queue_item()
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.side_effect = TgRateLimitError(retry_after_sec=5.0)

        render_fn = MagicMock(return_value="<b>alert</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act & Assert: TgRateLimitError propagates to caller
        with pytest.raises(TgRateLimitError):
            await workflow.tick()

        # The item must be requeued before the error propagates
        queue.enqueue.assert_called_once_with(item)

    @pytest.mark.asyncio
    async def test_tg_rate_limit_error_has_retry_after(self) -> None:
        """
        Given gateway raises TgRateLimitError(retry_after_sec=30),
        When tick() is called and the error propagates,
        Then the caught error has retry_after_sec=30 (caller can use it for backoff).
        """
        # Arrange
        item = _make_queue_item()
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = None

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.side_effect = TgRateLimitError(retry_after_sec=30.0)

        render_fn = MagicMock(return_value="<b>x</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        with pytest.raises(TgRateLimitError) as exc_info:
            await workflow.tick()

        # Assert
        assert exc_info.value.retry_after_sec == 30.0


# ---------------------------------------------------------------------------
# test_dispatch_stores_message_id_on_first_send
# ---------------------------------------------------------------------------


class TestDispatchStoresMessageIdOnFirstSend:
    @pytest.mark.asyncio
    async def test_message_id_stored_in_dedup_entry_after_send(self) -> None:
        """
        Given a queue item with fingerprint=fp-xyz and no existing dedup entry,
        When tick() calls send_message() returning message_id=777,
        Then the dedup entry for fp-xyz has message_id=777.
        """
        # Arrange
        fp = "fp-xyz"
        item = _make_queue_item(fingerprint=fp, action="new_alert")
        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        # Real DedupCache so we can inspect the stored entry
        real_cache = DedupCache()
        real_cache.classify(
            fingerprint=fp, severity="error", event={"msg": "boom"}, now=0.0
        )

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 777

        render_fn = MagicMock(return_value="<b>new alert</b>")

        workflow = DispatchLoopWorkflow(
            _queue=queue,
            _rate_bucket=rate_bucket,
            _dedup_cache=real_cache,
            _render_fn=render_fn,
            _gateway=gateway,
            _chat_id="-100abc",
            _telegram_io=_make_facade(),
        )

        # Act
        await workflow.tick()

        # Assert
        entry = real_cache.get_entry(fp)
        assert entry is not None
        assert entry.message_id == 777


# ---------------------------------------------------------------------------
# test_dispatch_uses_message_id_for_edits
# ---------------------------------------------------------------------------


class TestDispatchUsesMessageIdForEdits:
    @pytest.mark.asyncio
    async def test_edit_message_called_for_counter_edit_with_message_id(self) -> None:
        """
        Given a queue item with action=counter_edit and a dedup entry with message_id=555,
        When tick() is called,
        Then gateway.edit_message_text() is called (not send_message).
        """
        # Arrange
        fp = "fp-edit"
        item = _make_queue_item(fingerprint=fp, action="counter_edit")
        # Override action in payload
        item.payload["action"] = "counter_edit"

        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        # Mock dedup entry with an existing message_id
        existing_entry = MagicMock(spec=DedupEntry)
        existing_entry.message_id = 555

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = existing_entry

        gateway = AsyncMock(spec=ITelegramGateway)
        render_fn = MagicMock(return_value="<b>counter: 5</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        await workflow.tick()

        # Assert: edit used, not send
        gateway.edit_message_text.assert_called_once()
        gateway.send_message.assert_not_called()

        # And it was called with the right message_id
        call_kwargs = gateway.edit_message_text.call_args.kwargs
        assert call_kwargs["message_id"] == 555

    @pytest.mark.asyncio
    async def test_send_message_called_for_counter_edit_without_message_id(
        self,
    ) -> None:
        """
        Given a queue item with action=counter_edit but dedup entry has message_id=None,
        When tick() is called,
        Then gateway.send_message() is called (fallback to new message).
        """
        # Arrange
        fp = "fp-no-msg"
        item = _make_queue_item(fingerprint=fp, action="counter_edit")
        item.payload["action"] = "counter_edit"

        queue = MagicMock(spec=CentralQueue)
        queue.dequeue.return_value = item

        rate_bucket = MagicMock(spec=RateBucket)
        rate_bucket.acquire.return_value = True

        # Dedup entry exists but has no message_id yet
        existing_entry = MagicMock(spec=DedupEntry)
        existing_entry.message_id = None

        dedup_cache = MagicMock(spec=DedupCache)
        dedup_cache.get_entry.return_value = existing_entry

        gateway = AsyncMock(spec=ITelegramGateway)
        gateway.send_message.return_value = 100

        render_fn = MagicMock(return_value="<b>alert</b>")

        workflow = _make_workflow(
            queue=queue,
            rate_bucket=rate_bucket,
            dedup_cache=dedup_cache,
            render_fn=render_fn,
            gateway=gateway,
        )

        # Act
        await workflow.tick()

        # Assert: falls back to send
        gateway.send_message.assert_called_once()
        gateway.edit_message_text.assert_not_called()
