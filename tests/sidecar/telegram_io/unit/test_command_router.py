"""Unit tests for CommandRouter budget rejection path.

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §13.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.telegram_io.adapters.driving.command_router import CommandRouter


def _make_router(
    *,
    budget_allows: bool = True,
    rate_msg: str = "⏳ rate-limited, retry in 6s",
) -> tuple[CommandRouter, MagicMock, MagicMock, dict[str, AsyncMock]]:
    """Return (router, gateway_mock, status_uc_mock, all_handlers)."""
    budget = MagicMock()
    budget.acquire = MagicMock(return_value=budget_allows)
    budget.rate_limited_message = MagicMock(return_value=rate_msg)

    gateway = MagicMock()
    gateway.send_message = AsyncMock()

    status_uc = AsyncMock(return_value={"text": "status ok", "parse_mode": "HTML"})
    last_uc = AsyncMock(return_value={"text": "last ok", "parse_mode": "HTML"})
    test_uc = AsyncMock(return_value={"text": "test ok", "parse_mode": "HTML"})
    mute_uc = AsyncMock(return_value={"text": "muted", "parse_mode": "HTML"})
    unmute_uc = AsyncMock(return_value={"text": "unmuted", "parse_mode": "HTML"})
    chart_uc = AsyncMock(return_value={"text": "chart", "parse_mode": "HTML"})
    export_uc = AsyncMock(return_value={"text": "exported", "parse_mode": "HTML"})

    router = CommandRouter(
        _status_query=status_uc,
        _last_query=last_uc,
        _test_uc=test_uc,
        _mute_uc=mute_uc,
        _unmute_uc=unmute_uc,
        _chart_query=chart_uc,
        _export_query=export_uc,
        _gateway=gateway,
        _chat_id="123",
        _command_budget=budget,
    )
    handlers = {
        "status": status_uc,
        "last": last_uc,
        "test": test_uc,
        "mute": mute_uc,
        "unmute": unmute_uc,
        "chart": chart_uc,
        "export": export_uc,
    }
    return router, gateway, status_uc, handlers


class TestCommandRouterBudgetRejection:
    @pytest.mark.asyncio
    async def test_budget_exhausted_sends_rate_limit_message_not_uc(self) -> None:
        """
        Given budget is exhausted (acquire returns False),
        When /status message arrives,
        Then router sends the rate-limit message and does NOT call the UC.
        """
        rate_msg = "⏳ rate-limited, retry in 6s"
        router, gateway, status_uc, _ = _make_router(
            budget_allows=False, rate_msg=rate_msg,
        )

        message = {"text": "/status", "message_id": 42}
        await router.handle(message)

        gateway.send_message.assert_awaited_once_with(
            chat_id="123",
            text=rate_msg,
            parse_mode="HTML",
        )
        status_uc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_budget_available_calls_uc_not_rate_limit(self) -> None:
        """
        Given budget has tokens (acquire returns True),
        When /status message arrives,
        Then router calls the UC and does NOT send a rate-limit message.
        """
        router, gateway, status_uc, _ = _make_router(budget_allows=True)

        message = {"text": "/status", "message_id": 1}
        await router.handle(message)

        status_uc.assert_awaited_once()
        # gateway.send_message called once for the UC reply, not a rate-limit
        gateway.send_message.assert_awaited_once()
        call_kwargs = gateway.send_message.call_args.kwargs
        assert "rate-limited" not in call_kwargs.get("text", "")

    @pytest.mark.asyncio
    async def test_budget_exhausted_stateful_command_says_not_processed(self) -> None:
        """
        Given budget is exhausted,
        When /mute message arrives,
        Then rate_limited_message is called with 'mute' (stateful variant).
        """
        rate_msg = "⏳ Command rate-limited. /mute not processed. Retry in 6s."
        router, gateway, _, _ = _make_router(budget_allows=False, rate_msg=rate_msg)

        message = {"text": "/mute a1b2c3 1h", "message_id": 7}
        await router.handle(message)

        gateway.send_message.assert_awaited_once_with(
            chat_id="123",
            text=rate_msg,
            parse_mode="HTML",
        )


class TestCommandRouterThreadIdPropagation:
    """F-T13: command router forwards ``message_thread_id`` to every slash UC."""

    @pytest.mark.asyncio
    async def test_status_receives_message_thread_id(self) -> None:
        """
        Given a /status message arriving on a forum topic (message_thread_id=42),
        When the router dispatches it,
        Then the status UC is awaited with message_thread_id=42.
        """
        router, _, _, handlers = _make_router(budget_allows=True)

        message = {"text": "/status", "message_id": 1, "message_thread_id": 42}
        await router.handle(message)

        handlers["status"].assert_awaited_once_with(args="", message_thread_id=42)

    @pytest.mark.asyncio
    async def test_test_receives_message_thread_id(self) -> None:
        """
        Given a /test message on a forum topic,
        When the router dispatches it,
        Then the test UC is awaited with both message_id and message_thread_id.
        """
        router, _, _, handlers = _make_router(budget_allows=True)

        message = {"text": "/test", "message_id": 9, "message_thread_id": 42}
        await router.handle(message)

        handlers["test"].assert_awaited_once_with(
            message_id=9, message_thread_id=42,
        )

    @pytest.mark.asyncio
    async def test_missing_message_thread_id_propagates_as_none(self) -> None:
        """
        Given a /last message without message_thread_id (private/group chat),
        When the router dispatches it,
        Then the UC is awaited with message_thread_id=None.
        """
        router, _, _, handlers = _make_router(budget_allows=True)

        message = {"text": "/last 10", "message_id": 3}
        await router.handle(message)

        handlers["last"].assert_awaited_once_with(args="10", message_thread_id=None)

    @pytest.mark.asyncio
    async def test_all_slash_uc_kinds_receive_thread_id(self) -> None:
        """
        Given each supported slash command arrives on topic 7,
        When the router dispatches them,
        Then every UC is awaited with message_thread_id=7.
        """
        router, _, _, handlers = _make_router(budget_allows=True)

        commands = {
            "status": ("/status", "status"),
            "last": ("/last", "last"),
            "mute": ("/mute a1b2c3 1h", "mute"),
            "unmute": ("/unmute a1b2c3", "unmute"),
            "chart": ("/chart cpu 5m", "chart"),
            "export": ("/export", "export"),
        }
        for text, uc_key in commands.values():
            message = {"text": text, "message_id": 1, "message_thread_id": 7}
            await router.handle(message)
            handlers[uc_key].assert_awaited()
            assert handlers[uc_key].call_args.kwargs["message_thread_id"] == 7
