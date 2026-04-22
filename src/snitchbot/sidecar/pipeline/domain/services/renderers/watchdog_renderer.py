"""Watchdog event renderer."""
from ..html_escape_service import escape_html
from ..severity_icon_service import severity_icon
from ._common import _MAX_STUCK_TASKS, _render_details, _render_header

__all__ = ["render_watchdog"]


def render_watchdog(event: dict, dedup_entry: dict, service: str) -> str:
    payload = event["payload"]
    count = dedup_entry["count"]
    fingerprint = event.get("fingerprint", "")
    icon = severity_icon(dedup_entry["severity"])

    header = _render_header(
        icon=icon,
        kind_label="watchdog",
        service=service,
        fingerprint=fingerprint,
        count=count,
    )

    block_ms = payload.get("block_duration_ms", 0)
    threshold_ms = payload.get("threshold_ms", 0)
    title = f"Event loop blocked for <b>{block_ms:.0f} ms</b> (threshold {threshold_ms:.0f} ms)"

    loop_id = escape_html(payload.get("loop_id", "main"))
    extra_lines = [f"  loop   {loop_id}"]
    details = _render_details(
        ts=event.get("ts", 0.0),
        pid=event.get("pid", 0),
        count=count,
        first_seen=dedup_entry["first_seen"],
        last_seen=dedup_entry["last_seen"],
        extra_lines=extra_lines,
    )

    # Stuck tasks block
    stuck_tasks = payload.get("stuck_tasks", [])
    n_total = len(stuck_tasks)
    tasks_block = None
    if stuck_tasks:
        shown = stuck_tasks[:_MAX_STUCK_TASKS]
        task_lines = []
        for task in shown:
            name = escape_html(task.get("name", ""))
            coro = escape_html(task.get("coro", ""))
            task_lines.append(f"{name} · {coro}")
            stack = task.get("stack", [])
            if stack:
                task_lines.append(f"  {escape_html(stack[0])}")
        tasks_block = (
            f"<b>Stuck tasks</b> ({n_total})\n<pre>\n"
            + "\n".join(task_lines)
            + "\n</pre>"
        )

    parts = [header, title, details]
    if tasks_block:
        parts.append(tasks_block)

    return "\n".join(parts)
