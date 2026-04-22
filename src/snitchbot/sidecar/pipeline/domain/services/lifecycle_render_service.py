"""Lifecycle render service.

Pure domain service. No I/O, no frameworks. Stdlib only.

Lifecycle events use a separate, simpler template:
- No severity icon (🟠/🔴/🟣)
- No fingerprint, no counter
- No inline buttons
- No Details first/last block
- No Context block
"""
from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_utc

from .html_escape_service import escape_html

__all__ = ["render_lifecycle"]

def render_lifecycle(*, event: dict, service: str) -> str:
    """Render a lifecycle event message as HTML for Telegram.

    R5: no severity icon, no counter, no fingerprint, no buttons.

    Supported lifecycle states:
    - startup -> ▶ <b>service started</b>
    - shutdown graceful (sigterm/clean_exit) -> ■ <b>service stopped</b>
    - shutdown crash -> ⚠ <b>service crashed</b>
    """
    payload = event.get("payload", {})
    phase = payload.get("phase", "startup")
    reason = payload.get("reason", "init")
    exit_code = payload.get("exit_code")
    role = payload.get("role", "standalone")
    pid = event.get("pid", 0)
    ts = event.get("ts", 0.0)
    service_safe = escape_html(service)
    time_str = fmt_utc(ts)

    # Show role in heading for non-standalone processes
    role_suffix = f" ({escape_html(role)})" if role and role != "standalone" else ""

    if phase == "startup":
        heading = f"▶ <b>{service_safe}{role_suffix} started</b>"
        body_lines = [
            f"pid        {pid}",
            f"time       {time_str}",
        ]
    elif phase == "shutdown" and reason == "crash":
        heading = f"⚠ <b>{service_safe}{role_suffix} crashed</b>"
        body_lines = [
            f"pid        {pid}",
            f"reason     {escape_html(reason)}",
            f"time       {time_str}",
        ]
    elif phase == "shutdown" and reason == "killed":
        heading = f"⚠ <b>{service_safe}{role_suffix} killed</b>"
        body_lines = [
            f"pid        {pid}",
            f"reason     {escape_html(reason)}",
            f"time       {time_str}",
        ]
    else:
        # graceful shutdown: sigterm, clean_exit
        heading = f"■ <b>{service_safe}{role_suffix} stopped</b>"
        body_lines = [
            f"pid        {pid}",
            f"reason     {escape_html(reason)}",
        ]
        if exit_code is not None:
            body_lines.append(f"exit_code  {exit_code}")
        body_lines.append(f"time       {time_str}")

    body = "\n".join(body_lines)
    return f"{heading}\n{SEPARATOR}\n{body}"
