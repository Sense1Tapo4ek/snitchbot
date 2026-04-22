"""httpx-based Telegram Bot API gateway.

- All methods are async.
- 429 -> TgRateLimitError with retry_after (Invariant RL6).
- Network/timeout -> TgNetworkError.
- Latency tracked in ring buffer (last 10 calls, in milliseconds).
"""

import time

import httpx

from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import (
    TgApiError,
    TgNetworkError,
    TgPermissionError,
    TgRateLimitError,
    TgThreadNotFoundError,
)

_RING_SIZE = 10


class TgGatewayHttpx:
    """Telegram Bot API gateway via httpx."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._base = f"{base_url}/bot{token}"
        self._client = httpx.AsyncClient(timeout=30.0)
        self._latencies: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
        message_thread_id: int | None = None,
    ) -> int:
        """Send a message. Returns Telegram message_id."""
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id

        data = await self._post("sendMessage", payload)
        return data["result"]["message_id"]

    async def pin_chat_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        disable_notification: bool = True,
    ) -> None:
        """Pin a message in the chat (or topic of the message). Idempotent server-side."""
        await self._post("pinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
        })

    async def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> None:
        """Edit an existing message."""
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        await self._post("editMessageText", payload)

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: int,
        reply_markup: dict,
    ) -> None:
        """Edit an existing message's inline keyboard."""
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        }
        await self._post("editMessageReplyMarkup", payload)

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> None:
        """Answer an inline-button callback query. Invariant RL8."""
        payload: dict = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }
        await self._post("answerCallbackQuery", payload)

    async def send_document(
        self,
        *,
        chat_id: str,
        document: bytes,
        filename: str,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> int:
        """Send a file as document via multipart upload."""
        start = time.monotonic()
        try:
            files = {"document": (filename, document)}
            data: dict = {"chat_id": chat_id}
            if caption is not None:
                data["caption"] = caption
            if message_thread_id is not None:
                data["message_thread_id"] = message_thread_id
            resp = await self._client.post(
                f"{self._base}/sendDocument",
                data=data,
                files=files,
            )
        except httpx.TimeoutException as exc:
            raise TgNetworkError(f"Timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TgNetworkError(f"Network error: {exc}") from exc
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._latencies.append(elapsed_ms)
            if len(self._latencies) > _RING_SIZE:
                self._latencies.pop(0)

        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 1)
            raise TgRateLimitError(float(retry_after))

        if resp.status_code != 200:
            description = resp.json().get("description", "unknown")
            lo = description.lower()
            if "not enough rights to manage topics" in lo:
                raise TgPermissionError(description)
            if "message thread not found" in lo:
                raise TgThreadNotFoundError(description)
            raise TgApiError(resp.status_code, description)

        return resp.json()["result"]["message_id"]

    async def set_my_commands(
        self,
        *,
        commands: list[dict],
        scope: dict | None = None,
    ) -> None:
        """Register bot commands. Invariant T8."""
        payload: dict = {"commands": commands}
        if scope is not None:
            payload["scope"] = scope

        await self._post("setMyCommands", payload)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 60,
    ) -> list[dict]:
        """Long-poll for updates."""
        payload: dict = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset

        data = await self._post("getUpdates", payload)
        return data["result"]

    async def get_chat(self, *, chat_id: str) -> dict:
        """Return the Chat object — used at startup to detect is_forum."""
        data = await self._post("getChat", {"chat_id": chat_id})
        return data["result"]

    async def get_me(self) -> dict:
        """Return the bot's own User object — used at startup to resolve its user_id."""
        data = await self._post("getMe", {})
        return data["result"]

    async def get_chat_member(self, *, chat_id: str, user_id: int) -> dict:
        """Return ChatMember for ``user_id`` in ``chat_id`` — used at startup
        to detect whether the bot has ``can_manage_topics`` admin right (F1)."""
        data = await self._post(
            "getChatMember",
            {"chat_id": chat_id, "user_id": user_id},
        )
        return data["result"]

    async def create_forum_topic(
        self,
        *,
        chat_id: str,
        name: str,
        icon_color: int,
        icon_custom_emoji_id: str | None = None,
    ) -> int:
        """Create a topic. Returns message_thread_id (Invariant F3)."""
        payload: dict = {"chat_id": chat_id, "name": name, "icon_color": icon_color}
        if icon_custom_emoji_id is not None:
            payload["icon_custom_emoji_id"] = icon_custom_emoji_id
        data = await self._post("createForumTopic", payload)
        return int(data["result"]["message_thread_id"])

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def latencies(self) -> list[float]:
        """Copy of the ring buffer (ms, last 10 calls)."""
        return list(self._latencies)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(self, method: str, payload: dict) -> dict:
        start = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self._base}/{method}",
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise TgNetworkError(f"Timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TgNetworkError(f"Network error: {exc}") from exc
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._latencies.append(elapsed_ms)
            if len(self._latencies) > _RING_SIZE:
                self._latencies.pop(0)

        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 1)
            raise TgRateLimitError(float(retry_after))

        if resp.status_code != 200:
            description = resp.json().get("description", "unknown")
            lo = description.lower()
            if "not enough rights to manage topics" in lo:
                raise TgPermissionError(description)
            if "message thread not found" in lo:
                raise TgThreadNotFoundError(description)
            raise TgApiError(resp.status_code, description)

        return resp.json()
