"""Integration tests for TgGatewayHttpx — Task 8.1, 15 tests.

Uses pytest-httpx to intercept HTTP calls without touching the real Telegram API.
All tests follow Given/When/Then docstrings and Arrange/Act/Assert structure.
"""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import (
    TgApiError,
    TgNetworkError,
    TgRateLimitError,
)
from snitchbot.sidecar.telegram_io.ports.driven.tg_gateway_httpx import TgGatewayHttpx

BASE_URL = "https://api.telegram.org"
TOKEN = "test-token-123"


def _gw() -> TgGatewayHttpx:
    return TgGatewayHttpx(token=TOKEN, base_url=BASE_URL)


def _bot_url(method: str) -> str:
    return f"{BASE_URL}/bot{TOKEN}/{method}"


def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_html_parse_mode(httpx_mock: HTTPXMock) -> None:
    """
    Given a gateway and a plain text,
    When send_message is called with default parse_mode,
    Then the HTTP payload contains parse_mode='HTML'.
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        json=_ok({"message_id": 1}),
    )

    gw = _gw()
    await gw.send_message(chat_id="-100", text="hello")
    await gw.close()

    request = httpx_mock.get_requests()[0]
    body = request.read()
    import json
    payload = json.loads(body)
    assert payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_message_with_reply_markup(httpx_mock: HTTPXMock) -> None:
    """
    Given a gateway and an inline keyboard dict,
    When send_message is called with reply_markup,
    Then the HTTP payload contains the reply_markup field.
    """
    keyboard = {"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        json=_ok({"message_id": 42}),
    )

    gw = _gw()
    await gw.send_message(chat_id="-100", text="pick one", reply_markup=keyboard)
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["reply_markup"] == keyboard


@pytest.mark.asyncio
async def test_send_message_returns_message_id(httpx_mock: HTTPXMock) -> None:
    """
    Given a successful Telegram response with message_id=77,
    When send_message is awaited,
    Then the return value is 77.
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        json=_ok({"message_id": 77}),
    )

    gw = _gw()
    result = await gw.send_message(chat_id="-100", text="hi")
    await gw.close()

    assert result == 77


@pytest.mark.asyncio
async def test_send_message_reply_to(httpx_mock: HTTPXMock) -> None:
    """
    Given a reply_to_message_id=5,
    When send_message is called,
    Then the HTTP payload contains reply_to_message_id=5.
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        json=_ok({"message_id": 10}),
    )

    gw = _gw()
    await gw.send_message(chat_id="-100", text="reply", reply_to_message_id=5)
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["reply_to_message_id"] == 5


# ---------------------------------------------------------------------------
# edit_message_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_message_text_api_shape(httpx_mock: HTTPXMock) -> None:
    """
    Given chat_id, message_id, and new text,
    When edit_message_text is called,
    Then editMessageText is POSTed with the correct fields.
    """
    httpx_mock.add_response(
        url=_bot_url("editMessageText"),
        json=_ok({"message_id": 3}),
    )

    gw = _gw()
    await gw.edit_message_text(chat_id="-100", message_id=3, text="updated")
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["chat_id"] == "-100"
    assert payload["message_id"] == 3
    assert payload["text"] == "updated"
    assert payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_edit_message_reply_markup(httpx_mock: HTTPXMock) -> None:
    """
    Given a reply_markup dict,
    When edit_message_text is called with it,
    Then the payload includes reply_markup.
    """
    keyboard = {"inline_keyboard": [[{"text": "X", "callback_data": "x"}]]}
    httpx_mock.add_response(
        url=_bot_url("editMessageText"),
        json=_ok({"message_id": 7}),
    )

    gw = _gw()
    await gw.edit_message_text(
        chat_id="-100", message_id=7, text="new", reply_markup=keyboard
    )
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["reply_markup"] == keyboard


# ---------------------------------------------------------------------------
# answer_callback_query (RL8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_callback_query_shape(httpx_mock: HTTPXMock) -> None:
    """
    Given a callback_query_id and a text response,
    When answer_callback_query is called,
    Then answerCallbackQuery is POSTed with correct fields.
    Invariant RL8.
    """
    httpx_mock.add_response(
        url=_bot_url("answerCallbackQuery"),
        json=_ok(True),
    )

    gw = _gw()
    await gw.answer_callback_query(callback_query_id="cq-1", text="Muted!")
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["callback_query_id"] == "cq-1"
    assert payload["text"] == "Muted!"
    assert payload["show_alert"] is False


# ---------------------------------------------------------------------------
# Error handling (RL6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_raises_TgRateLimitError_with_retry_after(
    httpx_mock: HTTPXMock,
) -> None:
    """
    Given Telegram responds 429 with retry_after=30,
    When any API method is called,
    Then TgRateLimitError is raised with retry_after_sec=30.0.
    Invariant RL6.
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        status_code=429,
        json={"ok": False, "parameters": {"retry_after": 30}},
    )

    gw = _gw()
    with pytest.raises(TgRateLimitError) as exc_info:
        await gw.send_message(chat_id="-100", text="hi")
    await gw.close()

    assert exc_info.value.retry_after_sec == 30.0


@pytest.mark.asyncio
async def test_429_without_retry_after_defaults_1s(httpx_mock: HTTPXMock) -> None:
    """
    Given Telegram responds 429 with no retry_after field,
    When any API method is called,
    Then TgRateLimitError.retry_after_sec defaults to 1.0.
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        status_code=429,
        json={"ok": False},
    )

    gw = _gw()
    with pytest.raises(TgRateLimitError) as exc_info:
        await gw.send_message(chat_id="-100", text="hi")
    await gw.close()

    assert exc_info.value.retry_after_sec == 1.0


@pytest.mark.asyncio
async def test_network_error_raises_TgNetworkError(httpx_mock: HTTPXMock) -> None:
    """
    Given an httpx.ConnectError during the request,
    When send_message is awaited,
    Then TgNetworkError is raised.
    """
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=_bot_url("sendMessage"),
    )

    gw = _gw()
    with pytest.raises(TgNetworkError):
        await gw.send_message(chat_id="-100", text="hi")
    await gw.close()


@pytest.mark.asyncio
async def test_timeout_raises_TgNetworkError(httpx_mock: HTTPXMock) -> None:
    """
    Given an httpx.TimeoutException during the request,
    When send_message is awaited,
    Then TgNetworkError is raised.
    """
    httpx_mock.add_exception(
        httpx.TimeoutException("read timeout"),
        url=_bot_url("sendMessage"),
    )

    gw = _gw()
    with pytest.raises(TgNetworkError):
        await gw.send_message(chat_id="-100", text="hi")
    await gw.close()


# ---------------------------------------------------------------------------
# Latency ring buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_recorded(httpx_mock: HTTPXMock) -> None:
    """
    Given a gateway with no prior calls,
    When one successful send_message completes,
    Then latencies list has exactly one entry (in milliseconds, > 0).
    """
    httpx_mock.add_response(
        url=_bot_url("sendMessage"),
        json=_ok({"message_id": 1}),
    )

    gw = _gw()
    await gw.send_message(chat_id="-100", text="hi")
    await gw.close()

    assert len(gw.latencies) == 1
    assert gw.latencies[0] > 0


@pytest.mark.asyncio
async def test_latency_ring_buffer_last_10(httpx_mock: HTTPXMock) -> None:
    """
    Given 12 successful calls,
    When latencies is checked,
    Then only the last 10 are retained.
    """
    for _ in range(12):
        httpx_mock.add_response(
            url=_bot_url("sendMessage"),
            json=_ok({"message_id": 1}),
        )

    gw = _gw()
    for i in range(12):
        await gw.send_message(chat_id="-100", text=f"msg {i}")
    await gw.close()

    assert len(gw.latencies) == 10


# ---------------------------------------------------------------------------
# set_my_commands (T8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_my_commands_shape(httpx_mock: HTTPXMock) -> None:
    """
    Given a list of bot commands,
    When set_my_commands is called,
    Then setMyCommands is POSTed with the commands list.
    Invariant T8.
    """
    commands = [
        {"command": "mute", "description": "Mute alerts"},
        {"command": "unmute", "description": "Unmute alerts"},
    ]
    httpx_mock.add_response(
        url=_bot_url("setMyCommands"),
        json=_ok(True),
    )

    gw = _gw()
    await gw.set_my_commands(commands=commands)
    await gw.close()

    import json
    payload = json.loads(httpx_mock.get_requests()[0].read())
    assert payload["commands"] == commands


@pytest.mark.asyncio
async def test_set_my_commands_failure_not_fatal(httpx_mock: HTTPXMock) -> None:
    """
    Given Telegram returns an error for setMyCommands,
    When set_my_commands is called,
    Then TgApiError is raised (not silenced) — the caller decides fatality.
    """
    httpx_mock.add_response(
        url=_bot_url("setMyCommands"),
        status_code=400,
        json={"ok": False, "description": "Bad Request: invalid command"},
    )

    gw = _gw()
    with pytest.raises(TgApiError) as exc_info:
        await gw.set_my_commands(commands=[{"command": "x", "description": "y"}])
    await gw.close()

    assert exc_info.value.status_code == 400
