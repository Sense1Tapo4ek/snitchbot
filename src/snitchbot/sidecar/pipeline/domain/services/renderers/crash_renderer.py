"""Crash event renderer."""
from ..html_escape_service import escape_html
from ..severity_icon_service import severity_icon
from ._common import (
    _render_context,
    _render_details,
    _render_header,
    _render_stack_frames,
)

__all__ = ["render_crash"]


def render_crash(event: dict, dedup_entry: dict, service: str) -> str:
    payload = event["payload"]
    count = dedup_entry["count"]
    fingerprint = event.get("fingerprint", "")
    icon = severity_icon(dedup_entry["severity"])

    # Header (R3, R8)
    header = _render_header(
        icon=icon,
        kind_label="crash",
        service=service,
        fingerprint=fingerprint,
        count=count,
    )

    # Title
    exc_type = escape_html(payload.get("exception_type", ""))
    msg = escape_html(payload.get("message", ""))
    title = f"<b>{exc_type}</b>: {msg}"

    # Details
    extra_lines = [
        f"  thread   {escape_html(payload.get('thread', ''))}",
        f"  origin   {escape_html(payload.get('origin', ''))}",
    ]
    details = _render_details(
        ts=event.get("ts", 0.0),
        pid=event.get("pid", 0),
        count=count,
        first_seen=dedup_entry["first_seen"],
        last_seen=dedup_entry["last_seen"],
        extra_lines=extra_lines,
    )

    # Context (R10)
    context_block = _render_context(event.get("context"))

    # Stack
    stack = payload.get("stack", [])
    stack_block = _render_stack_frames(stack) if stack else None

    parts = [header, title, details]
    if context_block:
        parts.append(context_block)
    if stack_block:
        parts.append(stack_block)

    return "\n".join(parts)
