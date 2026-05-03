"""Flow tests for StatusQuery (/status command).

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §4.
Plan: Task 9.3.

Invariants validated: §4.4 health cue rules.
"""
from unittest.mock import MagicMock

import pytest

from snitchbot.sidecar.interactive.app.use_cases.status_query import StatusQuery
from snitchbot.sidecar.interactive.domain.recent_events_buffer_agg import (
    RecentEvent,
    RecentEventsBuffer,
)
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(started_at: float = 1_000_000.0, pid: int = 12345) -> MagicMock:
    s = MagicMock()
    s.started_at = started_at
    s.pid = pid
    s.first_hello_received = True
    s.dispatch_degraded = False
    s.app_total_rss_bytes = 0
    s.app_total_cpu_percent = 0.0
    s.app_children_count = 0
    return s


def _make_registry(pids: list[int] | None = None) -> MagicMock:
    r = MagicMock()
    pids = pids or []
    r.all_pids.return_value = pids

    def get_by_pid(p):
        import time
        c = MagicMock()
        c.role = "worker"
        c.last_seen = time.time()
        c.latest_vitals = None
        c.vitals_status = "ok"
        return c

    r.get_by_pid.side_effect = get_by_pid
    return r


def _make_queue(depth: int = 0, max_size: int = 256) -> MagicMock:
    q = MagicMock()
    q.__len__ = MagicMock(return_value=depth)
    q.max_size = max_size
    return q


def _make_dedup(count: int = 0) -> MagicMock:
    d = MagicMock()
    d.__len__ = MagicMock(return_value=count)
    return d


def _make_rate_bucket(tokens: int = 28, max_tokens: int = 30) -> MagicMock:
    rb = MagicMock()
    rb.tokens = tokens
    rb.max_tokens = max_tokens
    return rb


def _make_status_query(
    *,
    registry=None,
    session=None,
    queue=None,
    dedup=None,
    rate_bucket=None,
    mute_state=None,
    recent_buffer=None,
    stats=None,
    service="orders-api",
    lib_version="0.1.0",
    now: float = 1_004_000.0,
) -> tuple[StatusQuery, float]:
    if registry is None:
        registry = _make_registry()
    if session is None:
        session = _make_session()
    if queue is None:
        queue = _make_queue()
    if dedup is None:
        dedup = _make_dedup()
    if rate_bucket is None:
        rate_bucket = _make_rate_bucket()
    if mute_state is None:
        mute_state = MuteState()
    if recent_buffer is None:
        recent_buffer = RecentEventsBuffer()
    if stats is None:
        stats = {"dropped": 0}

    config = MagicMock()
    config.service = service

    uc = StatusQuery(
        _registry=registry,
        _session=session,
        _queue=queue,
        _dedup_cache=dedup,
        _rate_bucket=rate_bucket,
        _mute_state=mute_state,
        _recent_buffer=recent_buffer,
        _stats=stats,
        _config=config,
        _lib_version=lib_version,
    )
    return uc, now


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStatusDefaultWindow:
    @pytest.mark.asyncio
    async def test_status_default_window_1h(self) -> None:
        """
        Given /status with no args,
        When executed,
        Then response uses default 1h window (no error).
        """
        uc, now = _make_status_query()
        result = await uc(args="", now=now)
        assert "text" in result
        assert "❌" not in result["text"]
        assert "1h" in result["text"] or "Traffic" in result["text"]


class TestStatusRendersBlocks:
    @pytest.mark.asyncio
    async def test_status_renders_sidecar_block(self) -> None:
        """
        Given a running sidecar session,
        When /status is called,
        Then response includes Sidecar block with uptime, lib, pid.
        """
        uc, now = _make_status_query(lib_version="0.1.0")
        result = await uc(args="", now=now)
        text = result["text"]
        assert "Sidecar" in text
        assert "0.1.0" in text
        assert "uptime" in text.lower()

    @pytest.mark.asyncio
    async def test_status_renders_traffic_counters(self) -> None:
        """
        Given a recent buffer with some errors,
        When /status is called,
        Then response shows traffic counters block.
        """
        buf = RecentEventsBuffer()
        buf.add(RecentEvent(
            ts=1_003_999.0,  # within 1h of now=1_004_000
            fingerprint="abc123",
            severity="error",
            exception_type="ValueError",
            message="bad",
            pid=101,
            kind="crash",
        ))
        uc, now = _make_status_query(recent_buffer=buf)
        result = await uc(args="", now=now)
        text = result["text"]
        assert "Traffic" in text
        assert "errors" in text


class TestStatusHealthCue:
    @pytest.mark.asyncio
    async def test_status_health_cue_green(self) -> None:
        """
        Given no drops, queue < 50%, clients alive,
        When /status called,
        Then health cue is 🟢.
        """
        registry = _make_registry(pids=[101, 102])
        uc, now = _make_status_query(
            registry=registry,
            queue=_make_queue(depth=10, max_size=256),
            stats={"dropped": 0},
        )
        result = await uc(args="", now=now)
        assert "🟢" in result["text"]

    @pytest.mark.asyncio
    async def test_status_health_cue_yellow_when_dropped(self) -> None:
        """
        Given dropped > 0,
        When /status called,
        Then health cue is 🟡.
        """
        registry = _make_registry(pids=[101])
        uc, now = _make_status_query(
            registry=registry,
            stats={"dropped": 5},
        )
        result = await uc(args="", now=now)
        assert "🟡" in result["text"]

    @pytest.mark.asyncio
    async def test_status_health_cue_red_when_no_clients(self) -> None:
        """
        Given all clients dead (empty registry, first hello already received),
        When /status called,
        Then health cue is 🔴.
        """
        session = _make_session()
        session.first_hello_received = True
        uc, now = _make_status_query(
            registry=_make_registry(pids=[]),
            session=session,
            stats={"dropped": 0},
        )
        result = await uc(args="", now=now)
        assert "🔴" in result["text"]


class TestStatusInvalidWindow:
    @pytest.mark.asyncio
    async def test_status_invalid_window_returns_error(self) -> None:
        """
        Given /status 5min (invalid format),
        When executed,
        Then error message returned.
        """
        uc, now = _make_status_query()
        result = await uc(args="5min", now=now)
        assert "❌" in result["text"]
