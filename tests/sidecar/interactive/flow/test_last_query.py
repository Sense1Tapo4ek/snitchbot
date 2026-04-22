"""Flow tests for LastQuery (/last command).

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §5.
Plan: Task 9.4.
"""
from unittest.mock import MagicMock

import pytest

from snitchbot.sidecar.interactive.app.use_cases.last_query import LastQuery
from snitchbot.sidecar.interactive.domain.recent_events_buffer_agg import (
    RecentEvent,
    RecentEventsBuffer,
)

_NOW = 1_004_000.0


def _make_recent_event(
    fp: str = "abc123",
    severity: str = "error",
    ts_offset: float = -10.0,
    message: str = "something broke",
    count: int = 1,
) -> RecentEvent:
    return RecentEvent(
        ts=_NOW + ts_offset,
        fingerprint=fp,
        severity=severity,
        exception_type="ValueError",
        message=message,
        pid=101,
        kind="crash",
        count=count,
    )


def _make_uc(
    *,
    buffer: RecentEventsBuffer | None = None,
    service: str = "orders-api",
) -> LastQuery:
    if buffer is None:
        buffer = RecentEventsBuffer()
    config = MagicMock()
    config.service = service
    return LastQuery(
        _recent_buffer=buffer,
        _config=config,
    )


class TestLastDefaultArgs:
    @pytest.mark.asyncio
    async def test_last_default_n5_window_1h(self) -> None:
        """
        Given buffer with 10 errors within 1h,
        When /last with no args,
        Then returns at most 5 events.
        """
        buf = RecentEventsBuffer()
        for i in range(10):
            buf.add(_make_recent_event(fp=f"fp{i:04}", ts_offset=-float(i * 60)))
        uc = _make_uc(buffer=buf)
        result = await uc(args="", now=_NOW)
        text = result["text"]
        # Should have at most 5 entries (default N=5)
        fp_count = text.count("<code>")
        assert fp_count <= 5

    @pytest.mark.asyncio
    async def test_last_with_N_20_max(self) -> None:
        """
        Given /last 20,
        When executed with 25 errors in buffer,
        Then returns at most 20 (max cap).
        """
        buf = RecentEventsBuffer()
        for i in range(25):
            buf.add(_make_recent_event(fp=f"fp{i:04}", ts_offset=-float(i * 10)))
        uc = _make_uc(buffer=buf)
        result = await uc(args="20", now=_NOW)
        assert "❌" not in result["text"]
        fp_count = result["text"].count("<code>")
        assert fp_count <= 20

    @pytest.mark.asyncio
    async def test_last_exceeds_20_capped_at_20(self) -> None:
        """
        Given /last 50 (beyond max),
        When executed,
        Then max cap is applied (returns at most 20).
        """
        buf = RecentEventsBuffer()
        for i in range(30):
            buf.add(_make_recent_event(fp=f"fp{i:04}", ts_offset=-float(i * 10)))
        uc = _make_uc(buffer=buf)
        result = await uc(args="50", now=_NOW)
        fp_count = result["text"].count("<code>")
        assert fp_count <= 20


class TestLastEmpty:
    @pytest.mark.asyncio
    async def test_last_empty_no_errors(self) -> None:
        """
        Given empty buffer,
        When /last called,
        Then single-line "No errors" response returned.
        """
        uc = _make_uc(buffer=RecentEventsBuffer())
        result = await uc(args="", now=_NOW)
        text = result["text"]
        assert "No errors" in text or "No events" in text
        # Should be a short single-line response
        assert len(text) < 200

    @pytest.mark.asyncio
    async def test_last_empty_all_flag(self) -> None:
        """
        Given /last all with empty buffer,
        When executed,
        Then returns "No events" message.
        """
        uc = _make_uc(buffer=RecentEventsBuffer())
        result = await uc(args="all", now=_NOW)
        text = result["text"]
        assert "No" in text


class TestLastTruncation:
    @pytest.mark.asyncio
    async def test_last_truncates_at_4096(self) -> None:
        """
        Given many large events,
        When /last produces text > 4096 chars,
        Then result is truncated with indicator.
        """
        buf = RecentEventsBuffer()
        for i in range(20):
            buf.add(RecentEvent(
                ts=_NOW - i * 10,
                fingerprint=f"fp{i:04}",
                severity="error",
                exception_type="SomeVeryLongExceptionTypeNameThatMakesTextBig",
                message="x" * 200,
                pid=101,
                kind="crash",
                count=i + 1,
            ))
        uc = _make_uc(buffer=buf)
        result = await uc(args="20", now=_NOW)
        assert len(result["text"]) <= 4096


class TestLastInvalidArgs:
    @pytest.mark.asyncio
    async def test_last_invalid_window_returns_error(self) -> None:
        """
        Given /last 5min (invalid),
        When executed,
        Then error message returned.
        """
        uc = _make_uc()
        result = await uc(args="5min", now=_NOW)
        assert "❌" in result["text"]
