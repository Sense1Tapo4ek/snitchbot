"""Slow-call event renderer."""
from ..html_escape_service import escape_html
from ..severity_icon_service import severity_icon
from ._common import _render_context, _render_details, _render_header

__all__ = ["render_slow_call"]


def render_slow_call(event: dict, dedup_entry: dict, service: str) -> str:
    payload = event["payload"]
    count = dedup_entry["count"]
    fingerprint = event.get("fingerprint", "")
    icon = severity_icon(dedup_entry["severity"])

    header = _render_header(
        icon=icon,
        kind_label="slow call",
        service=service,
        fingerprint=fingerprint,
        count=count,
    )

    func = escape_html(payload.get("func_qualname", ""))
    duration = payload.get("duration_ms", 0)
    threshold = payload.get("threshold_ms", 0)
    title = f"<b>{func}</b> took {duration:.0f} ms (threshold {threshold:.0f} ms)"

    location = payload.get("location") or {}
    loc_file = location.get("file", "")
    loc_line = location.get("line", "")
    is_async = payload.get("is_async", False)
    extra_lines = [
        f"  is_async  {'true' if is_async else 'false'}",
        f"  location  {escape_html(loc_file)}:{loc_line}",
    ]
    details = _render_details(
        ts=event.get("ts", 0.0),
        pid=event.get("pid", 0),
        count=count,
        first_seen=dedup_entry["first_seen"],
        last_seen=dedup_entry["last_seen"],
        extra_lines=extra_lines,
    )

    parts = [header, title, details]

    # Context block (R10) — attached from request_context if present
    context_block = _render_context(event.get("context"))
    if context_block:
        parts.append(context_block)

    return "\n".join(parts)
