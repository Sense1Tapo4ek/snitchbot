"""Flow tests for LiveMessageUpdaterWorkflow — Task 11.2.

Spec: docs/superpowers/specs/2026-04-11-live-message-vitals-design.md §5.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 11.2.

Invariants validated: LM1, LM2, LM3, LM4, LM5, LM6, LM7.

All external interfaces (ITelegramGateway) replaced with AsyncMock/MagicMock.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.shared.domain.client_state import ClientState
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.live_message.app.workflows.live_message_updater_workflow import (
    LIVE_MESSAGE_TICK_SEC,
    LiveMessageUpdaterWorkflow,
)
from snitchbot.sidecar.live_message.domain.live_message_state_agg import LiveMessageState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0
_SERVICE = "orders-api"
_CHAT_ID = "123456"


def _make_vitals(rss_bytes: int = 80 * 1024 * 1024) -> VitalsSnapshot:
    return VitalsSnapshot(
        sampled_at=_NOW,
        rss_bytes=rss_bytes,
        cpu_percent=5.0,
        threads=8,
        fds=12,
    )


def _make_client(
    pid: int = 1234,
    vitals: VitalsSnapshot | None = None,
    vitals_status: str = "ok",
) -> ClientState:
    c = ClientState(
        pid=pid,
        role="master",
        service=_SERVICE,
        last_seen=_NOW,
        connected_at=_NOW - 60,
    )
    c.vitals_status = vitals_status
    c.latest_vitals = vitals if vitals is not None else _make_vitals()
    return c


def _make_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.send_message = AsyncMock(return_value=42)  # returns message_id
    gw.edit_message_text = AsyncMock(return_value=None)
    gw.pin_chat_message = AsyncMock(return_value=None)
    return gw


def _make_telegram_io() -> MagicMock:
    """Simple-mode facade stub: resolve_topic always returns None."""
    facade = MagicMock()
    facade.resolve_topic = AsyncMock(return_value=None)
    return facade


def _make_workflow(
    *,
    gateway: AsyncMock | None = None,
    state: LiveMessageState | None = None,
) -> LiveMessageUpdaterWorkflow:
    gw = gateway or _make_gateway()
    st = state or LiveMessageState(service=_SERVICE)
    return LiveMessageUpdaterWorkflow(
        _gateway=gw,
        _telegram_io=_make_telegram_io(),
        _chat_id=_CHAT_ID,
        _service=_SERVICE,
        _state=st,
        _sidecar_started_at=_NOW - 3600,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTickInterval:
    def test_tick_10s_fixed(self):
        """
        Given the module constant LIVE_MESSAGE_TICK_SEC,
        When inspected,
        Then it equals 10 (LM2).
        """
        assert LIVE_MESSAGE_TICK_SEC == 10


class TestCreateOnFirstSample:
    @pytest.mark.asyncio
    async def test_created_only_after_first_vitals_sample(self):
        """
        Given no clients (no vitals yet),
        When tick is called,
        Then send_message is NOT called (LM5).
        """
        gw = _make_gateway()
        wf = _make_workflow(gateway=gw)
        await wf.tick(clients={}, now=_NOW)
        gw.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_called_on_first_client_with_vitals(self):
        """
        Given a client with latest_vitals set,
        When tick is called for the first time,
        Then send_message is called once and message_id is stored (LM5).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        wf = _make_workflow(gateway=gw, state=state)
        clients = {1234: _make_client()}
        await wf.tick(clients=clients, now=_NOW)
        gw.send_message.assert_called_once()
        assert state.get_message_id(_CHAT_ID, None) == 42


class TestContentHashSkip:
    @pytest.mark.asyncio
    async def test_content_hash_compare_skips_noop_edits(self):
        """
        Given same content rendered twice at the same timestamp,
        When tick is called twice with identical vitals and same 'now',
        Then edit_message_text is not called (second call is a no-op) (LM3).

        Note: 'now' must be identical to ensure the 'updated' timestamp
        in the rendered HTML stays the same (spec §5.7 rounding applies to
        vitals; the timestamp itself changes on each wall-clock second).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        wf = _make_workflow(gateway=gw, state=state)
        clients = {1234: _make_client()}

        # First tick — creates message
        await wf.tick(clients=clients, now=_NOW)
        assert state.get_message_id(_CHAT_ID, None) == 42

        # Second tick — identical now and vitals -> same rendered HTML -> skip edit
        await wf.tick(clients=clients, now=_NOW)
        gw.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_called_when_content_changes(self):
        """
        Given a message already exists,
        When tick is called with different vitals (rss changed),
        Then edit_message_text is called once (LM3 — content changed).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        wf = _make_workflow(gateway=gw, state=state)
        clients = {1234: _make_client(vitals=_make_vitals(rss_bytes=80 * 1024 * 1024))}

        # First tick — creates
        await wf.tick(clients=clients, now=_NOW)

        # Change vitals significantly (different MB)
        clients[1234].latest_vitals = _make_vitals(rss_bytes=200 * 1024 * 1024)
        await wf.tick(clients=clients, now=_NOW + 10)
        gw.edit_message_text.assert_called_once()


class TestRssRounding:
    @pytest.mark.asyncio
    async def test_rounding_rss_to_MB_cpu_to_1_decimal_for_stable_hash(self):
        """
        Given clients with rss differing by < 1MB and cpu by < 0.1%,
        When tick is called twice at the same 'now' (so 'updated' timestamp is stable),
        Then second tick is a no-op (hash stable due to vitals rounding) (spec §5.7).

        Note: 'now' is kept identical across both ticks so the 'updated' timestamp
        in the rendered HTML does not change. The test specifically validates that
        sub-1MB RSS and sub-0.1% CPU fluctuations do not cause spurious edits.
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        wf = _make_workflow(gateway=gw, state=state)

        base_rss = 100 * 1024 * 1024  # 100 MB exactly
        clients = {1234: _make_client(vitals=VitalsSnapshot(
            sampled_at=_NOW,
            rss_bytes=base_rss,
            cpu_percent=5.0,
            threads=8,
            fds=12,
        ))}
        await wf.tick(clients=clients, now=_NOW)

        # Sub-1MB and sub-0.1% change — rounds to same display values
        clients[1234].latest_vitals = VitalsSnapshot(
            sampled_at=_NOW + 5,
            rss_bytes=base_rss + 500 * 1024,  # +500KB -> still 100 MB after // 1024**2
            cpu_percent=5.04,                  # rounds to "5.0%" with :.1f
            threads=8,
            fds=12,
        )
        # Same now -> 'updated' timestamp identical -> hash depends only on vitals display
        await wf.tick(clients=clients, now=_NOW)
        gw.edit_message_text.assert_not_called()


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_final_edit_red_header_stopped_at_time(self):
        """
        Given an existing live message,
        When shutdown_edit is called,
        Then edit_message_text is called with text containing 🔴 and 'stopped' (LM6).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        state.set_message_id(_CHAT_ID, None, 99)
        state.set_content_hash(_CHAT_ID, None, "oldhash")
        wf = _make_workflow(gateway=gw, state=state)

        await wf.shutdown_edit(now=_NOW)
        gw.edit_message_text.assert_called_once()
        call_kwargs = gw.edit_message_text.call_args.kwargs
        assert "🔴" in call_kwargs["text"]
        assert "stopped" in call_kwargs["text"].lower()

    @pytest.mark.asyncio
    async def test_shutdown_edit_noop_when_no_message_exists(self):
        """
        Given no live message (message_id is None),
        When shutdown_edit is called,
        Then edit_message_text is NOT called.
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)  # message_id=None
        wf = _make_workflow(gateway=gw, state=state)
        await wf.shutdown_edit(now=_NOW)
        gw.edit_message_text.assert_not_called()


class TestCrashNewSession:
    @pytest.mark.asyncio
    async def test_crash_leaves_old_message_new_sidecar_creates_new(self):
        """
        Given a fresh workflow (no message_id — simulating new sidecar session),
        When tick is called with clients,
        Then send_message is called (creates NEW message) (LM7).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)  # fresh — no message_id
        wf = _make_workflow(gateway=gw, state=state)
        clients = {1234: _make_client()}
        await wf.tick(clients=clients, now=_NOW)
        gw.send_message.assert_called_once()


class TestOneMessagePerService:
    @pytest.mark.asyncio
    async def test_one_live_message_per_service(self):
        """
        Given a live message already exists (message_id set),
        When tick is called with changed content,
        Then send_message is NOT called again (one message per service) (LM1).
        """
        gw = _make_gateway()
        state = LiveMessageState(service=_SERVICE)
        state.set_message_id(_CHAT_ID, None, 77)
        wf = _make_workflow(gateway=gw, state=state)
        clients = {1234: _make_client()}
        await wf.tick(clients=clients, now=_NOW)
        gw.send_message.assert_not_called()
        # edit_message_text may or may not be called (depends on hash), but send never again
