import pytest
from pytest_httpx import HTTPXMock

from snitchbot.sidecar.telegram_io.ports.driven.tg_gateway_httpx import TgGatewayHttpx
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import (
    TgPermissionError,
    TgThreadNotFoundError,
)


@pytest.mark.asyncio
class TestTgGatewayForum:
    async def test_get_chat_returns_is_forum_flag(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/getChat",
            json={"ok": True, "result": {"id": -1001, "type": "supergroup", "is_forum": True}},
        )
        chat = await gw.get_chat(chat_id="-1001")
        assert chat["is_forum"] is True
        assert chat["type"] == "supergroup"

    async def test_create_forum_topic_returns_message_thread_id(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/createForumTopic",
            json={"ok": True, "result": {
                "message_thread_id": 77, "name": "orders-api",
                "icon_color": 9367192, "icon_custom_emoji_id": None,
            }},
        )
        thread_id = await gw.create_forum_topic(
            chat_id="-1001", name="orders-api", icon_color=9367192,
        )
        assert thread_id == 77

    async def test_send_message_passes_message_thread_id(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/sendMessage",
            json={"ok": True, "result": {"message_id": 5}},
        )
        await gw.send_message(chat_id="-1001", text="hi", message_thread_id=42)
        sent = httpx_mock.get_requests()[0]
        body = sent.read()
        assert b'"message_thread_id":42' in body or b'"message_thread_id": 42' in body

    async def test_send_message_omits_thread_id_when_none(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/sendMessage",
            json={"ok": True, "result": {"message_id": 5}},
        )
        await gw.send_message(chat_id="-1001", text="hi")
        sent = httpx_mock.get_requests()[0]
        assert b"message_thread_id" not in sent.read()

    async def test_create_forum_topic_permission_error(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/createForumTopic",
            status_code=400,
            json={"ok": False, "description":
                  "Bad Request: not enough rights to manage topics"},
        )
        with pytest.raises(TgPermissionError):
            await gw.create_forum_topic(chat_id="-1001", name="x", icon_color=9367192)

    async def test_pin_chat_message_posts_chat_and_message_id(
        self, httpx_mock: HTTPXMock,
    ):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/pinChatMessage",
            json={"ok": True, "result": True},
        )
        await gw.pin_chat_message(chat_id="-1001", message_id=42)
        sent = httpx_mock.get_requests()[0]
        body = sent.read()
        assert b'"chat_id":"-1001"' in body or b'"chat_id": "-1001"' in body
        assert b'"message_id":42' in body or b'"message_id": 42' in body
        # Default disable_notification=True
        assert b'"disable_notification":true' in body or b'"disable_notification": true' in body

    async def test_pin_chat_message_permission_error(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/pinChatMessage",
            status_code=400,
            json={"ok": False, "description":
                  "Bad Request: not enough rights to manage topics"},
        )
        with pytest.raises(TgPermissionError):
            await gw.pin_chat_message(chat_id="-1001", message_id=42)

    async def test_send_message_thread_not_found(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/sendMessage",
            status_code=400,
            json={"ok": False, "description":
                  "Bad Request: message thread not found"},
        )
        with pytest.raises(TgThreadNotFoundError):
            await gw.send_message(chat_id="-1001", text="hi", message_thread_id=999)

    async def test_get_me_returns_bot_user(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/getMe",
            json={"ok": True, "result": {
                "id": 12345, "is_bot": True,
                "first_name": "Snitch", "username": "snitch_bot",
            }},
        )
        me = await gw.get_me()
        assert me["id"] == 12345
        assert me["is_bot"] is True
        assert me["username"] == "snitch_bot"

    async def test_get_chat_member_returns_rights(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/getChatMember",
            json={"ok": True, "result": {
                "user": {"id": 12345, "is_bot": True},
                "status": "administrator",
                "can_manage_topics": True,
            }},
        )
        member = await gw.get_chat_member(chat_id="-1001", user_id=12345)
        assert member["status"] == "administrator"
        assert member["can_manage_topics"] is True

    async def test_get_chat_member_posts_user_id(self, httpx_mock: HTTPXMock):
        gw = TgGatewayHttpx(token="T")
        httpx_mock.add_response(
            url="https://api.telegram.org/botT/getChatMember",
            json={"ok": True, "result": {
                "user": {"id": 9, "is_bot": True},
                "status": "member",
            }},
        )
        await gw.get_chat_member(chat_id="-1001", user_id=9)
        sent = httpx_mock.get_requests()[-1]
        body = sent.read()
        assert b'"user_id":9' in body or b'"user_id": 9' in body
        assert b'"chat_id":"-1001"' in body or b'"chat_id": "-1001"' in body
