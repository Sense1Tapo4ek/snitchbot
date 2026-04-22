"""Custom event renderer."""
from ..html_escape_service import escape_html
from ..severity_icon_service import severity_icon
from ._common import (
    _custom_kind_label,
    _render_context,
    _render_details,
    _render_header,
)

__all__ = ["render_custom"]


def render_custom(event: dict, dedup_entry: dict, service: str) -> str:
    payload = event["payload"]
    count = dedup_entry["count"]
    fingerprint = event.get("fingerprint", "")
    icon = severity_icon(dedup_entry["severity"])

    header = _render_header(
        icon=icon,
        kind_label=_custom_kind_label(payload, event),
        service=service,
        fingerprint=fingerprint,
        count=count,
    )

    # Title = user text
    title = escape_html(payload.get("text", ""))

    # Details
    caller = payload.get("caller") or {}
    caller_file = caller.get("file", "")
    caller_line = caller.get("line", "")
    caller_func = caller.get("func", "")
    extra_lines = []
    if caller_file:
        loc = f"{escape_html(caller_file)}:{caller_line} in {escape_html(caller_func)}()"
        extra_lines.append(f"  caller   {loc}")

    details = _render_details(
        ts=event.get("ts", 0.0),
        pid=event.get("pid", 0),
        count=count,
        first_seen=dedup_entry["first_seen"],
        last_seen=dedup_entry["last_seen"],
        extra_lines=extra_lines,
    )

    # Extras
    extras = payload.get("extras")
    extras_block = None
    if extras:
        lines = []
        for k, v in extras.items():
            k_safe = escape_html(str(k))
            v_safe = escape_html(str(v))
            lines.append(f"  {k_safe}   {v_safe}")
        extras_block = "<b>Extras</b>\n" + "\n".join(lines)

    # Context (R10)
    context_block = _render_context(event.get("context"))

    # Exception block (if exc_info was passed to notify)
    exception = payload.get("exception")
    exc_block = None
    if exception and isinstance(exception, dict):
        exc_type = escape_html(exception.get("type", ""))
        exc_msg = escape_html(exception.get("message", ""))
        exc_tb = exception.get("traceback", "")
        lines = [f"<b>Exception</b>: {exc_type}: {exc_msg}"]
        if exc_tb:
            # Truncate traceback to fit Telegram limits
            tb_safe = escape_html(exc_tb[-500:] if len(exc_tb) > 500 else exc_tb)
            lines.append(f"<pre>{tb_safe}</pre>")
        exc_block = "\n".join(lines)
    elif exception and isinstance(exception, str):
        # Legacy: plain string exception
        exc_block = f"<b>Exception</b>: {escape_html(exception)}"

    parts = [header, title, details]
    if extras_block:
        parts.append(extras_block)
    if context_block:
        parts.append(context_block)
    if exc_block:
        parts.append(exc_block)

    return "\n".join(parts)
