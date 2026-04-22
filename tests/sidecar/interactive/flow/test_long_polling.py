"""Flow tests for LongPollingController.

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §2, T1, T2.
Plan: Task 9.1.

Invariants validated: T1 (other-chat ignored), T2 (error doesn't break dispatch).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snitchbot.sidecar.telegram_io.adapters.driving.long_polling_controller import (
    LongPollingController,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_controller(
    *,
    gateway: AsyncMock | None = None,
    command_router: AsyncMock | None = None,
    callback_router: AsyncMock | None = None,
    chat_id: str = "-100123456",
    session: MagicMock | None = None,
    stats: dict | None = None,
    set_commands_fn: AsyncMock | None = None,
) -> LongPollingController:
    if gateway is None:
        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(return_value=[])
    if command_router is None:
        command_router = AsyncMock()
    if callback_router is None:
        callback_router = AsyncMock()
    if session is None:
        session = MagicMock()
    if stats is None:
        stats = {}
    return LongPollingController(
        _gateway=gateway,
        _command_router=command_router,
        _callback_router=callback_router,
        _chat_id=chat_id,
        _session=session,
        _stats=stats,
        _set_commands_fn=set_commands_fn,
    )


def _make_message_update(
    update_id: int = 1,
    chat_id: str = "-100123456",
    text: str = "/status",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 42,
            "chat": {"id": int(chat_id)},
            "text": text,
        },
    }


def _stopper(ctrl_ref: list, *, on_call: int = 1):
    """Return an async side_effect that stops the controller on `on_call`-th invocation."""
    call_num = [0]

    async def _fn(**kwargs):
        call_num[0] += 1
        if call_num[0] >= on_call and ctrl_ref:
            ctrl_ref[0].stop()
        return []

    return _fn


# ---------------------------------------------------------------------------
# Task 9.1: Long-polling
# ---------------------------------------------------------------------------

class TestLongPollingUsesGetUpdatesTimeout:
    @pytest.mark.asyncio
    async def test_long_polling_uses_get_updates_with_60s_timeout(self) -> None:
        """
        Given a running controller,
        When it polls for updates,
        Then it calls gateway.get_updates(timeout=60).
        """
        # Arrange
        ctrl_ref: list = []
        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=_stopper(ctrl_ref, on_call=1))

        ctrl = _make_controller(gateway=gateway)
        ctrl_ref.append(ctrl)

        # Act
        await ctrl.run()

        # Assert: get_updates was called with timeout=60
        assert gateway.get_updates.call_count >= 1
        first_call = gateway.get_updates.call_args_list[0]
        assert first_call.kwargs.get("timeout") == 60


class TestUpdatesFromOtherChatIgnored:
    """T1: Messages from non-configured chat_id are silently ignored."""

    @pytest.mark.asyncio
    async def test_updates_from_other_chat_ignored(self) -> None:
        """
        Given update from chat_id=-999999 (different from configured -100123456),
        When long_polling processes it,
        Then command_router.handle is NOT called.
        """
        # Arrange
        command_router = AsyncMock()
        other_update = _make_message_update(update_id=1, chat_id="-999999", text="/status")
        ctrl_ref: list = []
        call_num = [0]

        async def side_effect(**kwargs):
            call_num[0] += 1
            if call_num[0] == 1:
                return [other_update]
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=side_effect)

        ctrl = _make_controller(
            gateway=gateway,
            command_router=command_router,
            chat_id="-100123456",
        )
        ctrl_ref.append(ctrl)

        # Act
        await ctrl.run()

        # Assert — command_router not called for foreign chat
        command_router.handle.assert_not_called()


class TestErrorDoesNotBreakLoop:
    """T2: getUpdates error doesn't crash the loop."""

    @pytest.mark.asyncio
    async def test_error_does_not_break_loop(self) -> None:
        """
        Given getUpdates raises an exception on first call,
        When the loop recovers,
        Then it retries and processes second call successfully.
        """
        # Arrange
        command_router = AsyncMock()
        ok_update = _make_message_update(update_id=5, text="/status")
        ctrl_ref: list = []
        call_num = [0]

        async def side_effect(**kwargs):
            call_num[0] += 1
            if call_num[0] == 1:
                raise RuntimeError("connection reset")
            elif call_num[0] == 2:
                return [ok_update]
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=side_effect)

        stats: dict = {}
        ctrl = _make_controller(
            gateway=gateway,
            command_router=command_router,
            stats=stats,
        )
        ctrl_ref.append(ctrl)

        # Patch sleep to avoid real wait
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ctrl.run()

        # Assert: error counter incremented
        assert stats.get("long_polling_errors", 0) >= 1
        # And the loop continued and routed the valid update
        command_router.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_long_polling_stats_errors_incremented(self) -> None:
        """
        Given getUpdates fails N times,
        When the controller runs,
        Then stats['long_polling_errors'] == N.
        """
        # Arrange
        stats: dict = {}
        ctrl_ref: list = []
        call_num = [0]

        async def side_effect(**kwargs):
            call_num[0] += 1
            if call_num[0] <= 2:
                raise OSError("timeout")
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=side_effect)

        ctrl = _make_controller(gateway=gateway, stats=stats)
        ctrl_ref.append(ctrl)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ctrl.run()

        assert stats["long_polling_errors"] == 2


class TestBackoffSequence:
    @pytest.mark.asyncio
    async def test_backoff_1_2_4_8_30(self) -> None:
        """
        Given repeated getUpdates failures,
        When the controller backs off,
        Then sleep durations follow 1, 2, 4, 8, 30 sequence.
        """
        # Arrange
        ctrl_ref: list = []
        call_num = [0]

        async def side_effect(**kwargs):
            call_num[0] += 1
            if call_num[0] <= 5:
                raise OSError("fail")
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=side_effect)

        ctrl = _make_controller(gateway=gateway)
        ctrl_ref.append(ctrl)
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await ctrl.run()

        assert sleep_calls == [1, 2, 4, 8, 30]


class TestRecoveryAfterBackoff:
    @pytest.mark.asyncio
    async def test_recovery_after_backoff(self) -> None:
        """
        Given controller in backoff after errors,
        When getUpdates succeeds,
        Then normal processing resumes (updates are routed).
        """
        # Arrange
        command_router = AsyncMock()
        ok_update = _make_message_update(update_id=10)
        ctrl_ref: list = []
        call_num = [0]

        async def side_effect(**kwargs):
            call_num[0] += 1
            if call_num[0] == 1:
                raise RuntimeError("fail")
            elif call_num[0] == 2:
                return [ok_update]
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=side_effect)

        ctrl = _make_controller(gateway=gateway, command_router=command_router)
        ctrl_ref.append(ctrl)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ctrl.run()

        command_router.handle.assert_called_once()
