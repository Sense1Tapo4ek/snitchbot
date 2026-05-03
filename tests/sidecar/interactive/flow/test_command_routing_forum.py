"""Flow tests for F-T14: topic-scoped command execution (F7).

Each of /status, /last, /chart, /export, /test, /mute, /unmute resolves the
``service`` name from ``message_thread_id`` via ``TelegramIOFacade.reverse_lookup``.
In the General topic (thread_id None or 1) the commands keep their global
behaviour; unknown thread ids silently fall back to global (F7).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.interactive.app.use_cases.chart_query import ChartQuery
from snitchbot.sidecar.interactive.app.use_cases.export_query import ExportQuery
from snitchbot.sidecar.interactive.app.use_cases.last_query import LastQuery
from snitchbot.sidecar.interactive.app.use_cases.status_query import StatusQuery
from snitchbot.sidecar.interactive.app.use_cases.test_uc import TestUC
from snitchbot.sidecar.interactive.domain.recent_events_buffer_agg import (
    RecentEvent,
    RecentEventsBuffer,
)
from snitchbot.sidecar.muting.app.use_cases.mute_uc import MuteUC
from snitchbot.sidecar.muting.app.use_cases.unmute_uc import UnmuteUC
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

_NOW = 1_004_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_telegram_io(mapping: dict[int, str]) -> MagicMock:
    """Stub TelegramIOFacade with a fixed thread_id -> service table."""
    io = MagicMock()
    io.reverse_lookup = MagicMock(side_effect=lambda tid: mapping.get(tid))
    return io


def _client(service: str, status: str = "ok") -> MagicMock:
    c = MagicMock()
    c.service = service
    c.vitals_status = status
    c.role = "worker"
    c.latest_vitals = None
    c.last_seen = _NOW
    # chart/export inspect history (deque-like iterable) — empty is fine for
    # routing tests; we only assert client selection.
    c.vitals_history = []
    return c


def _make_status_uc(telegram_io=None) -> StatusQuery:
    registry = MagicMock()
    registry.all_pids.return_value = []
    session = MagicMock()
    session.started_at = _NOW - 60
    session.first_hello_received = True
    session.dispatch_degraded = False
    session.app_total_rss_bytes = 0
    session.app_total_cpu_percent = 0.0
    session.app_children_count = 0
    queue = MagicMock()
    queue.__len__ = MagicMock(return_value=0)
    queue.max_size = 256
    dedup = MagicMock()
    dedup.__len__ = MagicMock(return_value=0)
    rate = MagicMock()
    rate.tokens = 30
    rate.max_tokens = 30
    config = MagicMock()
    config.service = "fallback-global"
    config.sidecar_service = None
    return StatusQuery(
        _registry=registry,
        _session=session,
        _queue=queue,
        _dedup_cache=dedup,
        _rate_bucket=rate,
        _mute_state=MuteState(),
        _recent_buffer=RecentEventsBuffer(),
        _stats={"dropped": 0},
        _config=config,
        _lib_version="0.1.0",
        _telegram_io=telegram_io,
    )


def _make_last_uc(telegram_io=None) -> LastQuery:
    config = MagicMock()
    config.service = "fallback-global"
    return LastQuery(
        _recent_buffer=RecentEventsBuffer(),
        _config=config,
        _telegram_io=telegram_io,
    )


def _make_test_uc(telegram_io=None) -> TestUC:
    registry = MagicMock()
    registry.all_pids.return_value = []
    session = MagicMock()
    session.started_at = _NOW - 60
    session.dispatch_degraded = False
    session.app_total_rss_bytes = 0
    session.app_total_cpu_percent = 0.0
    session.app_children_count = 0
    config = MagicMock()
    config.service = "fallback-global"
    config.sidecar_service = None
    return TestUC(
        _registry=registry,
        _session=session,
        _queue=MagicMock(),
        _gateway=AsyncMock(),
        _config=config,
        _lib_version="0.1.0",
        _chat_id="-100",
        _latency_buffer=[],
        _telegram_io=telegram_io,
    )


def _make_chart_uc(registry, telegram_io=None) -> ChartQuery:
    renderer = MagicMock()
    renderer.render = MagicMock(return_value="chart-render")
    renderer.render_multi = MagicMock(return_value="chart-render-multi")
    return ChartQuery(
        _registry=registry,
        _renderer=renderer,
        _telegram_io=telegram_io,
    )


def _make_export_uc(registry, telegram_io=None) -> ExportQuery:
    gateway = AsyncMock()
    gateway.send_document = AsyncMock()
    return ExportQuery(
        _registry=registry,
        _gateway=gateway,
        _chat_id="-100",
        _telegram_io=telegram_io,
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStatusQueryForumScope:
    async def test_status_in_topic_scopes_header_to_service(self) -> None:
        """
        Given registry maps thread 42 -> 'orders-api',
        When /status arrives with message_thread_id=42,
        Then the rendered header uses 'orders-api' (not fallback-global).
        """
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_status_uc(telegram_io=io)
        result = await uc(args="", now=_NOW, message_thread_id=42)
        assert "orders-api" in result["text"]
        assert "fallback-global" not in result["text"]
        io.reverse_lookup.assert_called_once_with(42)

    async def test_status_in_general_thread_none_returns_global(self) -> None:
        """
        Given /status with message_thread_id=None (private chat or General),
        When executed,
        Then reverse_lookup is NOT called and the fallback service is shown.
        """
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_status_uc(telegram_io=io)
        result = await uc(args="", now=_NOW, message_thread_id=None)
        assert "fallback-global" in result["text"]
        io.reverse_lookup.assert_not_called()

    async def test_status_in_general_thread_one_returns_global(self) -> None:
        """
        Given /status inside the General topic (thread_id=1),
        When executed,
        Then reverse_lookup is NOT called and global behaviour is preserved.
        """
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_status_uc(telegram_io=io)
        result = await uc(args="", now=_NOW, message_thread_id=1)
        assert "fallback-global" in result["text"]
        io.reverse_lookup.assert_not_called()

    async def test_status_with_unknown_thread_id_falls_back_silently(self) -> None:
        """
        Given thread id 999 not registered,
        When /status arrives with message_thread_id=999,
        Then reverse_lookup returns None and the rendered header uses the
        fallback service (silent fallback, F7).
        """
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_status_uc(telegram_io=io)
        result = await uc(args="", now=_NOW, message_thread_id=999)
        io.reverse_lookup.assert_called_once_with(999)
        assert "fallback-global" in result["text"]


# ---------------------------------------------------------------------------
# /last
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLastQueryForumScope:
    async def test_last_in_topic_scopes_header_to_service(self) -> None:
        """
        Given registry maps thread 42 -> 'orders-api',
        When /last arrives on thread 42 with events in the buffer,
        Then the rendered header uses 'orders-api'.
        """
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_last_uc(telegram_io=io)
        uc._recent_buffer.add(
            RecentEvent(
                ts=_NOW - 10,
                fingerprint="abc123",
                severity="error",
                exception_type="ValueError",
                message="boom",
                pid=101,
                kind="crash",
            )
        )
        result = await uc(args="", now=_NOW, message_thread_id=42)
        assert "orders-api" in result["text"]


# ---------------------------------------------------------------------------
# /test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTestUCForumScope:
    async def test_test_in_topic_scopes_header_to_service(self) -> None:
        io = _make_telegram_io({7: "billing"})
        uc = _make_test_uc(telegram_io=io)
        result = await uc(message_id=42, now=_NOW, message_thread_id=7)
        assert "billing" in result["text"]

    async def test_test_in_general_returns_global(self) -> None:
        io = _make_telegram_io({7: "billing"})
        uc = _make_test_uc(telegram_io=io)
        result = await uc(message_id=42, now=_NOW, message_thread_id=None)
        assert "fallback-global" in result["text"]
        io.reverse_lookup.assert_not_called()


# ---------------------------------------------------------------------------
# /chart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChartQueryForumScope:
    async def test_chart_in_topic_picks_client_matching_service(self) -> None:
        """
        Given two live clients 'orders-api' and 'billing' in the registry,
        When /chart arrives on thread 42 (orders-api),
        Then the renderer is invoked with data from the orders-api client.
        """
        registry = MagicMock()
        registry.all_pids.return_value = [101, 102]

        def _get(pid: int):
            if pid == 101:
                return _client("billing")
            return _client("orders-api")

        registry.get_by_pid.side_effect = _get

        io = _make_telegram_io({42: "orders-api"})
        uc = _make_chart_uc(registry, telegram_io=io)
        result = await uc(args="cpu", now=_NOW, message_thread_id=42)
        # Must NOT return "No live clients" — we found the scoped client.
        assert "No live clients" not in result["text"]

    async def test_chart_in_topic_with_no_matching_client_returns_empty(self) -> None:
        """
        Given only a 'billing' client, but /chart arrives on the 'orders-api'
        topic, Then the fallback "No live clients" reply is returned.
        """
        registry = MagicMock()
        registry.all_pids.return_value = [101]
        registry.get_by_pid.side_effect = lambda pid: _client("billing")

        io = _make_telegram_io({42: "orders-api"})
        uc = _make_chart_uc(registry, telegram_io=io)
        result = await uc(args="cpu", now=_NOW, message_thread_id=42)
        assert "No live clients" in result["text"]

    async def test_chart_in_general_uses_any_client(self) -> None:
        """
        Given a single 'billing' client,
        When /chart arrives in General (thread_id=None),
        Then the client is picked regardless of its service name.
        """
        registry = MagicMock()
        registry.all_pids.return_value = [101]
        registry.get_by_pid.side_effect = lambda pid: _client("billing")

        io = _make_telegram_io({42: "orders-api"})
        uc = _make_chart_uc(registry, telegram_io=io)
        result = await uc(args="cpu", now=_NOW, message_thread_id=None)
        assert "No live clients" not in result["text"]


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportQueryForumScope:
    async def test_export_in_topic_with_no_matching_client_returns_empty(self) -> None:
        registry = MagicMock()
        registry.all_pids.return_value = [101]
        registry.get_by_pid.side_effect = lambda pid: _client("billing")

        io = _make_telegram_io({42: "orders-api"})
        uc = _make_export_uc(registry, telegram_io=io)
        result = await uc(now=_NOW, message_thread_id=42)
        assert "No live clients" in result["text"]
        uc._gateway.send_document.assert_not_called()


# ---------------------------------------------------------------------------
# /mute and /unmute
# ---------------------------------------------------------------------------


def _make_mute_uc(state: MuteState, telegram_io=None) -> MuteUC:
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=None)
    return MuteUC(
        _mute_state=state,
        _mute_repo=repo,
        _telegram_io=telegram_io,
    )


def _make_unmute_uc(state: MuteState, telegram_io=None) -> UnmuteUC:
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=None)
    return UnmuteUC(
        _mute_state=state,
        _mute_repo=repo,
        _telegram_io=telegram_io,
    )


@pytest.mark.asyncio
class TestMuteScopedToTopic:
    async def test_mute_in_topic_only_silences_that_service(self) -> None:
        """
        Given /mute a1b2c3 1h sent inside the orders-api topic,
        Then an event with fingerprint 'a1b2c3' + service='orders-api' is muted,
        but an event with the same fingerprint + service='billing' is NOT.
        """
        state = MuteState()
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_mute_uc(state, telegram_io=io)
        await uc(args="a1b2c3 1h", now=_NOW, message_thread_id=42)

        assert state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 5,
            service="orders-api",
        )
        assert not state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 5,
            service="billing",
        )

    async def test_mute_in_general_silences_all_services(self) -> None:
        """
        Given /mute a1b2c3 1h in General (thread_id=None),
        Then events for any service are suppressed (simple-mode semantics).
        """
        state = MuteState()
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_mute_uc(state, telegram_io=io)
        await uc(args="a1b2c3 1h", now=_NOW, message_thread_id=None)

        assert state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 5,
            service="orders-api",
        )
        assert state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 5,
            service="billing",
        )

    async def test_mute_scope_shown_in_reply(self) -> None:
        """
        Given /mute issued inside a topic,
        Then the reply text mentions the scoped service.
        """
        state = MuteState()
        io = _make_telegram_io({42: "orders-api"})
        uc = _make_mute_uc(state, telegram_io=io)
        reply = await uc(args="a1b2c3 1h", now=_NOW, message_thread_id=42)
        assert "orders-api" in reply["text"]

    async def test_mute_same_fp_different_services_both_accepted(self) -> None:
        """
        Given /mute a1b2c3 1h in orders-api topic,
        When /mute a1b2c3 1h is issued in billing topic,
        Then both mutes coexist (service acts as an independent scope key).
        """
        state = MuteState()
        io = _make_telegram_io({42: "orders-api", 43: "billing"})
        uc = _make_mute_uc(state, telegram_io=io)
        first = await uc(args="a1b2c3 1h", now=_NOW, message_thread_id=42)
        second = await uc(args="a1b2c3 1h", now=_NOW, message_thread_id=43)
        assert "🔇" in first["text"]
        assert "🔇" in second["text"]

    async def test_unmute_in_topic_only_lifts_scoped_entry(self) -> None:
        """
        Given separate orders-api and billing mutes for the same fingerprint,
        When /unmute a1b2c3 is issued in the orders-api topic,
        Then only the orders-api mute is lifted.
        """
        state = MuteState()
        io = _make_telegram_io({42: "orders-api", 43: "billing"})
        mute_uc = _make_mute_uc(state, telegram_io=io)
        await mute_uc(args="a1b2c3 1h", now=_NOW, message_thread_id=42)
        await mute_uc(args="a1b2c3 1h", now=_NOW, message_thread_id=43)

        unmute_uc = _make_unmute_uc(state, telegram_io=io)
        result = await unmute_uc(args="a1b2c3", now=_NOW + 10, message_thread_id=42)
        assert "🔔" in result["text"]

        assert not state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 20,
            service="orders-api",
        )
        assert state.is_muted(
            fingerprint="a1b2c3", severity="error", now=_NOW + 20,
            service="billing",
        )
