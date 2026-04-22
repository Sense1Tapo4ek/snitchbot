"""Flow tests for SetCommandsUC (setMyCommands).

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §12, T8.
Plan: Task 9.9.

Invariants validated: T8 (called on startup via entrypoint, not long_polling).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.telegram_io.adapters.driving.long_polling_controller import (
    LongPollingController,
)
from snitchbot.sidecar.telegram_io.app.use_cases.set_commands_uc import (
    BOT_COMMANDS,
    SetCommandsUC,
)

_CHAT_ID = "-100123456"


def _make_ctrl(
    gateway: AsyncMock,
    *,
    set_commands_fn=None,
    stats: dict | None = None,
) -> LongPollingController:
    return LongPollingController(
        _gateway=gateway,
        _command_router=AsyncMock(),
        _callback_router=AsyncMock(),
        _chat_id=_CHAT_ID,
        _session=MagicMock(),
        _stats=stats if stats is not None else {},
        _set_commands_fn=set_commands_fn,
    )


class TestSetMyCommands:
    @pytest.mark.asyncio
    async def test_set_my_commands_not_called_by_long_polling(self) -> None:
        """T8: setMyCommands is called at startup by the entrypoint, not by long_polling.

        Given LongPollingController with a set_commands_fn,
        When the first getUpdates returns successfully,
        Then set_commands_fn is NOT called by the controller (startup handles it).
        """
        set_commands_fn = AsyncMock(return_value=None)
        ctrl_ref: list = []

        async def get_updates_side(**kwargs):
            ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=get_updates_side)

        ctrl = _make_ctrl(gateway, set_commands_fn=set_commands_fn)
        ctrl_ref.append(ctrl)

        await ctrl.run()

        set_commands_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_long_polling_continues_normally_across_iterations(self) -> None:
        """
        Given multiple getUpdates calls,
        When the loop runs multiple iterations,
        Then the loop completes without error.
        """
        ctrl_ref: list = []
        call_num = [0]

        async def get_updates_side(**kwargs):
            call_num[0] += 1
            if call_num[0] >= 3:
                ctrl_ref[0].stop()
            return []

        gateway = AsyncMock()
        gateway.get_updates = AsyncMock(side_effect=get_updates_side)

        ctrl = _make_ctrl(gateway)
        ctrl_ref.append(ctrl)

        await ctrl.run()

        assert call_num[0] == 3

    @pytest.mark.asyncio
    async def test_set_commands_uc_calls_gateway(self) -> None:
        """
        Given SetCommandsUC with a gateway mock,
        When called,
        Then gateway.set_my_commands is called with correct scope.
        """
        gateway = AsyncMock()
        uc = SetCommandsUC(
            _gateway=gateway,
            _chat_id=_CHAT_ID,
        )
        await uc()
        gateway.set_my_commands.assert_called_once()
        call_kwargs = gateway.set_my_commands.call_args.kwargs
        assert call_kwargs["commands"] == BOT_COMMANDS
        scope = call_kwargs.get("scope", {})
        assert scope.get("type") == "chat"
        assert str(scope.get("chat_id")) == _CHAT_ID
