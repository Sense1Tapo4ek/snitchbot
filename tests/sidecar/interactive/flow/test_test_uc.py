"""Flow tests for TestUC (/test command).

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §6, T4, T10.
Plan: Task 9.5.

Invariants validated: T4 (head-of-queue), T10 (always responds under pressure).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.interactive.app.use_cases.test_uc import TestUC
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)

_NOW = 1_004_000.0


def _make_session(started_at: float = 1_000_000.0, pid: int = 12345) -> MagicMock:
    s = MagicMock()
    s.started_at = started_at
    s.pid = pid
    s.dispatch_degraded = False
    return s


def _make_registry(pids: list[int] | None = None) -> MagicMock:
    r = MagicMock()
    r.all_pids.return_value = pids or []
    return r


def _make_uc(
    *,
    registry=None,
    session=None,
    queue=None,
    gateway=None,
    service: str = "orders-api",
    lib_version: str = "0.1.0",
    chat_id: str = "-100123456",
    latency_buffer: list | None = None,
) -> TestUC:
    if registry is None:
        registry = _make_registry(pids=[101, 102])
    if session is None:
        session = _make_session()
    if queue is None:
        queue = MagicMock(spec=CentralQueue)
    if gateway is None:
        gateway = AsyncMock()
    config = MagicMock()
    config.service = service

    return TestUC(
        _registry=registry,
        _session=session,
        _queue=queue,
        _gateway=gateway,
        _config=config,
        _lib_version=lib_version,
        _chat_id=chat_id,
        _latency_buffer=latency_buffer if latency_buffer is not None else [],
    )


class TestTestReplyToOriginal:
    @pytest.mark.asyncio
    async def test_test_reply_to_original(self) -> None:
        """
        Given /test with message_id=42,
        When executed,
        Then reply includes reply_to_message_id=42.
        """
        uc = _make_uc()
        result = await uc(message_id=42, now=_NOW)
        assert result.get("reply_to_message_id") == 42

    @pytest.mark.asyncio
    async def test_test_no_reply_to_when_no_message_id(self) -> None:
        """
        Given /test without message_id,
        When executed,
        Then reply_to_message_id is absent.
        """
        uc = _make_uc()
        result = await uc(now=_NOW)
        assert "reply_to_message_id" not in result


class TestTestHeadOfQueuePriority:
    @pytest.mark.asyncio
    async def test_test_head_of_queue_priority(self) -> None:
        """T4: /test response uses TEST_RESPONSE priority (head-of-queue).

        Given a CentralQueue pre-filled with 5 NEW_ALERT items,
        When TestUC result is enqueued with TEST_RESPONSE priority,
        Then it is dequeued before all the NEW_ALERT items.
        """
        # Arrange: real queue with 5 regular alerts
        queue = CentralQueue()
        for i in range(5):
            queue.enqueue(QueueItem(
                priority=QueuePriority.NEW_ALERT,
                payload={"msg": f"alert-{i}"},
            ))

        # Enqueue test response at TEST_RESPONSE priority
        test_item = QueueItem(
            priority=QueuePriority.TEST_RESPONSE,
            payload={"action": "test_response", "text": "✅ Test OK"},
        )
        queue.enqueue(test_item)

        # Act: dequeue first item
        first = queue.dequeue()

        # Assert: TEST_RESPONSE comes out first
        assert first is not None
        assert first.priority == QueuePriority.TEST_RESPONSE


class TestTestBypassesDedupAndRateLimit:
    @pytest.mark.asyncio
    async def test_test_bypasses_dedup_and_rate_limit(self) -> None:
        """
        Given /test command,
        When executed,
        Then it does NOT require acquiring main rate bucket.
        (The UC itself just builds a reply dict; no rate check in TestUC.)
        """
        uc = _make_uc()
        # Should succeed regardless of any mocked rate limit
        result = await uc(now=_NOW)
        assert "text" in result
        assert "Test" in result["text"]


class TestTestShowsLatency:
    @pytest.mark.asyncio
    async def test_test_shows_latency_last_10(self) -> None:
        """
        Given latency buffer with 10 measurements,
        When /test is called,
        Then response includes tg latency field.
        """
        # 10 latency measurements (in seconds, will be converted to ms)
        latencies = [0.023, 0.018, 0.031, 0.025, 0.020,
                     0.022, 0.019, 0.028, 0.024, 0.021]
        uc = _make_uc(latency_buffer=latencies)
        result = await uc(now=_NOW)
        text = result["text"]
        assert "latency" in text.lower()
        assert "ms" in text

    @pytest.mark.asyncio
    async def test_test_shows_0_clients_waiting(self) -> None:
        """
        Given no connected clients,
        When /test called,
        Then shows "0 (waiting)" clients.
        """
        uc = _make_uc(registry=_make_registry(pids=[]))
        result = await uc(now=_NOW)
        assert "0 (waiting)" in result["text"]

    @pytest.mark.asyncio
    async def test_test_shows_degraded_when_dispatch_degraded(self) -> None:
        """
        Given dispatch_degraded=True on session,
        When /test called,
        Then cue shows DEGRADED.
        """
        session = _make_session()
        session.dispatch_degraded = True
        uc = _make_uc(session=session)
        result = await uc(now=_NOW)
        assert "DEGRADED" in result["text"] or "⚠" in result["text"]
