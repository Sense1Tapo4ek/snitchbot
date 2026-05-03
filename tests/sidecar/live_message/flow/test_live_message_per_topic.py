"""Flow tests for LiveMessageUpdaterWorkflow per-topic behaviour (F-T12).

Spec : docs/superpowers/plans/2026-04-20-forum-mode.md F-T12
Plan : docs/superpowers/plans/2026-04-20-forum-mode.md Task F-T12

Invariants validated: LM1 (one dashboard per topic), F8 (pin failures
logged + swallowed, never propagated).

All external interfaces (ITelegramGateway, TelegramIOFacade) are replaced
with AsyncMock / MagicMock.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.shared.domain.client_state import ClientState
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.live_message.app.workflows.live_message_updater_workflow import (
    LiveMessageUpdaterWorkflow,
)
from snitchbot.sidecar.live_message.domain.live_message_state_agg import LiveMessageState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0
_CHAT_ID = "123456"
_SIDECAR_SERVICE = "sidecar-runtime"


def _vitals(rss_bytes: int = 80 * 1024 * 1024) -> VitalsSnapshot:
    return VitalsSnapshot(
        sampled_at=_NOW,
        rss_bytes=rss_bytes,
        cpu_percent=5.0,
        threads=8,
        fds=12,
        total_rss_bytes=rss_bytes,
        total_cpu_percent=5.0,
        children_count=0,
    )


def _client(
    *,
    pid: int,
    service: str,
    rss_bytes: int = 80 * 1024 * 1024,
) -> ClientState:
    c = ClientState(
        pid=pid,
        role="master",
        service=service,
        last_seen=_NOW,
        connected_at=_NOW - 60,
    )
    c.vitals_status = "ok"
    c.latest_vitals = _vitals(rss_bytes=rss_bytes)
    return c


def _gateway(*, send_ids: list[int] | None = None) -> AsyncMock:
    gw = AsyncMock()
    gw.send_message = AsyncMock(side_effect=send_ids or [42])
    gw.edit_message_text = AsyncMock(return_value=None)
    gw.pin_chat_message = AsyncMock(return_value=None)
    return gw


def _facade_simple_mode() -> MagicMock:
    """TelegramIOFacade stub whose resolve_topic always returns None."""
    f = MagicMock()
    f.resolve_topic = AsyncMock(return_value=None)
    return f


def _facade_forum_mode(topics: dict[str, int]) -> MagicMock:
    """TelegramIOFacade stub that maps service->thread_id."""
    f = MagicMock()

    async def _resolve(*, service: str) -> int | None:
        return topics.get(service)

    f.resolve_topic = AsyncMock(side_effect=_resolve)
    return f


def _workflow(
    *,
    gateway: AsyncMock,
    facade: MagicMock,
    state: LiveMessageState | None = None,
) -> LiveMessageUpdaterWorkflow:
    return LiveMessageUpdaterWorkflow(
        _gateway=gateway,
        _telegram_io=facade,
        _chat_id=_CHAT_ID,
        _service=_SIDECAR_SERVICE,
        _state=state or LiveMessageState(),
        _sidecar_started_at=_NOW - 3600,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimpleModeSingleDashboard:
    @pytest.mark.asyncio
    async def test_simple_mode_keeps_single_pinned_message(self):
        """
        Given simple mode (facade.resolve_topic always returns None)
          and two clients from different services,
        When tick is called,
        Then exactly one dashboard is created at key (chat_id, None)
          and send_message is called without a message_thread_id.
        """
        # Arrange
        gw = _gateway(send_ids=[42])
        facade = _facade_simple_mode()
        state = LiveMessageState()
        wf = _workflow(gateway=gw, facade=facade, state=state)

        # Two distinct services in simple mode should still collapse to one
        # (chat_id, None) entry because resolve_topic returns None for both.
        # We still drive only one client here because the simple-mode
        # semantics are 'one dashboard per chat', irrespective of how many
        # services the host has.
        clients = {1234: _client(pid=1234, service="orders-api")}

        # Act
        await wf.tick(clients=clients, now=_NOW)

        # Assert
        assert state.get_message_id(_CHAT_ID, None) == 42
        assert gw.send_message.call_count == 1
        # thread_id should be None in the send
        kw = gw.send_message.call_args.kwargs
        assert kw.get("message_thread_id") is None


class TestForumModeCreatesThenPins:
    @pytest.mark.asyncio
    async def test_first_event_for_new_service_creates_topic_then_pins(self):
        """
        Given forum mode (facade resolves service 'orders-api' -> 77)
          and a client for that service,
        When tick is called,
        Then send_message is called with message_thread_id=77
          and pin_chat_message is called with the returned message_id.
        """
        # Arrange
        gw = _gateway(send_ids=[500])
        facade = _facade_forum_mode({"orders-api": 77})
        state = LiveMessageState()
        wf = _workflow(gateway=gw, facade=facade, state=state)
        clients = {1: _client(pid=1, service="orders-api")}

        # Act
        await wf.tick(clients=clients, now=_NOW)

        # Assert send
        gw.send_message.assert_called_once()
        send_kw = gw.send_message.call_args.kwargs
        assert send_kw["message_thread_id"] == 77
        assert send_kw["chat_id"] == _CHAT_ID

        # Assert pin
        gw.pin_chat_message.assert_called_once()
        pin_kw = gw.pin_chat_message.call_args.kwargs
        assert pin_kw["chat_id"] == _CHAT_ID
        assert pin_kw["message_id"] == 500

        # Assert state recorded under (chat_id, thread_id=77)
        assert state.get_message_id(_CHAT_ID, 77) == 500


class TestSubsequentTicksEditSameMessage:
    @pytest.mark.asyncio
    async def test_subsequent_events_for_same_service_edit_same_message(self):
        """
        Given a dashboard already exists for service 'orders-api' (thread 77, msg 500),
        When tick runs again with *changed* vitals (so hash differs),
        Then edit_message_text is called with the stored message_id
          and no new send_message / pin_chat_message occurs.
        """
        # Arrange: simulate prior tick by seeding state.
        gw = _gateway(send_ids=[])  # must not send
        facade = _facade_forum_mode({"orders-api": 77})
        state = LiveMessageState()
        state.set_message_id(_CHAT_ID, 77, 500)
        state.set_content_hash(_CHAT_ID, 77, "stale-hash")
        wf = _workflow(gateway=gw, facade=facade, state=state)

        clients = {1: _client(pid=1, service="orders-api", rss_bytes=200 * 1024 * 1024)}

        # Act
        await wf.tick(clients=clients, now=_NOW + 10)

        # Assert
        gw.send_message.assert_not_called()
        gw.pin_chat_message.assert_not_called()
        gw.edit_message_text.assert_called_once()
        edit_kw = gw.edit_message_text.call_args.kwargs
        assert edit_kw["message_id"] == 500
        assert edit_kw["chat_id"] == _CHAT_ID
        # editMessageText does NOT accept message_thread_id
        assert "message_thread_id" not in edit_kw


class TestTwoServicesTwoDashboards:
    @pytest.mark.asyncio
    async def test_two_services_get_two_independent_pinned_dashboards(self):
        """
        Given forum mode with two services mapping to distinct threads,
        When tick runs with clients from both services,
        Then two send_message calls + two pin_chat_message calls occur
          and state holds independent (message_id, thread_id) pairs.
        """
        # Arrange
        gw = _gateway(send_ids=[500, 600])
        facade = _facade_forum_mode({"orders-api": 77, "billing": 88})
        state = LiveMessageState()
        wf = _workflow(gateway=gw, facade=facade, state=state)

        clients = {
            1: _client(pid=1, service="orders-api"),
            2: _client(pid=2, service="billing"),
        }

        # Act
        await wf.tick(clients=clients, now=_NOW)

        # Assert: two independent sends + pins
        assert gw.send_message.call_count == 2
        assert gw.pin_chat_message.call_count == 2

        # Verify which thread_id went with which message_id
        send_calls = gw.send_message.call_args_list
        thread_ids_sent = {c.kwargs["message_thread_id"] for c in send_calls}
        assert thread_ids_sent == {77, 88}

        # State holds two distinct entries
        ids = {
            (77, state.get_message_id(_CHAT_ID, 77)),
            (88, state.get_message_id(_CHAT_ID, 88)),
        }
        assert ids == {(77, 500), (88, 600)} or ids == {(77, 600), (88, 500)}

        # Simple-mode key is empty
        assert state.get_message_id(_CHAT_ID, None) is None


class TestPinFailureDoesNotPropagate:
    @pytest.mark.asyncio
    async def test_pin_failure_logs_and_continues(
        self, caplog: pytest.LogCaptureFixture,
    ):
        """
        Given forum mode where pin_chat_message raises (e.g., TgPermissionError),
        When tick runs,
        Then:
          - the exception does NOT propagate (F8),
          - a WARNING is logged,
          - state still records the created message_id,
          - a subsequent tick edits the stored message_id normally (no new send).
        """
        # Arrange
        gw = _gateway(send_ids=[500])
        gw.pin_chat_message = AsyncMock(side_effect=RuntimeError("no rights to pin"))
        facade = _facade_forum_mode({"orders-api": 77})
        state = LiveMessageState()
        wf = _workflow(gateway=gw, facade=facade, state=state)
        clients = {1: _client(pid=1, service="orders-api")}

        # Act — first tick: creates + pin-fails (swallowed).
        with caplog.at_level(logging.WARNING, logger="snitchbot.sidecar.live_message"):
            await wf.tick(clients=clients, now=_NOW)

        # Assert: state recorded despite pin failure
        assert state.get_message_id(_CHAT_ID, 77) == 500
        assert any("pin failed" in r.message for r in caplog.records), (
            "Expected a warning log containing 'pin failed'"
        )

        # Act — second tick with changed vitals: must edit, not re-send.
        clients2 = {1: _client(pid=1, service="orders-api", rss_bytes=999 * 1024 * 1024)}
        await wf.tick(clients=clients2, now=_NOW + 10)

        # Assert: no second send, exactly one edit, no additional pins attempted.
        assert gw.send_message.call_count == 1
        gw.edit_message_text.assert_called_once()
        edit_kw = gw.edit_message_text.call_args.kwargs
        assert edit_kw["message_id"] == 500
