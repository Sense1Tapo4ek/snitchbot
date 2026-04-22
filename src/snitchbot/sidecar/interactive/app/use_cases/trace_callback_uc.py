"""TraceCallbackUC — handles the trace inline-button callback.

callback_data format: ``trace:<fingerprint>``. Sends the full traceback as a
new message wrapped in a ``<pre>`` block.
"""
from dataclasses import dataclass

from snitchbot.shared.constants import SEPARATOR, TG_MESSAGE_LIMIT
from snitchbot.sidecar.interactive.app.interfaces import (
    IDedupCache,
    ITelegramGateway,
)

__all__ = ["TraceCallbackUC"]


@dataclass(frozen=True, slots=True, kw_only=True)
class TraceCallbackUC:
    """Use case for trace inline button callback.

    Dependencies:
        _dedup_cache    : DedupCache (to look up latest event by fingerprint)
        _gateway        : ITelegramGateway
        _chat_id        : str
    """

    _dedup_cache: IDedupCache
    _gateway: ITelegramGateway
    _chat_id: str

    async def __call__(
        self,
        *,
        callback_query_id: str,
        fingerprint: str,
    ) -> None:
        """Handle trace callback: send full traceback as new message."""
        entry = self._dedup_cache.get_entry(fingerprint)

        if entry is None:
            await self._gateway.answer_callback_query(
                callback_query_id=callback_query_id,
                text="No trace available (event may have expired from dedup cache)",
                show_alert=True,
            )
            return

        # Extract stack from latest_event payload
        event = entry.latest_event or {}
        payload = event.get("payload", {})
        stack = payload.get("stack", None)

        if not stack:
            await self._gateway.answer_callback_query(
                callback_query_id=callback_query_id,
                text="No stack trace available for this event",
                show_alert=True,
            )
            return

        # Format traceback
        if isinstance(stack, list):
            stack_text = "\n".join(
                f"  File {frame.get('file','?')}:{frame.get('line','?')} in {frame.get('func','?')}"
                for frame in stack
            )
        else:
            stack_text = str(stack)

        exc_type = payload.get("exception_type", "Exception")
        exc_msg = payload.get("message", "")
        full_trace = (
            f"📋 <b>Traceback</b> · <code>{fingerprint}</code>\n"
            f"{SEPARATOR}\n"
            f"<pre>{exc_type}: {exc_msg}\n{stack_text}</pre>"
        )

        # Truncate to TG limit
        if len(full_trace) > TG_MESSAGE_LIMIT:
            full_trace = full_trace[:TG_MESSAGE_LIMIT - 36] + "\n… truncated</pre>"

        await self._gateway.send_message(
            chat_id=self._chat_id,
            text=full_trace,
            parse_mode="HTML",
        )

        await self._gateway.answer_callback_query(
            callback_query_id=callback_query_id,
            text="",
            show_alert=False,
        )
