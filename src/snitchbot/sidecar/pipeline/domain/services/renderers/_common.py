"""Shared helpers for all per-kind renderers.

Private module — not part of the public API.
"""
import time
from typing import Any

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_utc as _fmt_utc

from ..html_escape_service import escape_html

_MAX_CONTEXT_ENTRIES = 10
_MAX_STACK_FRAMES = 3
_MAX_STUCK_TASKS = 2


def _render_header(
    *,
    icon: str,
    kind_label: str,
    service: str,
    fingerprint: str,
    count: int,
) -> str:
    """Render the header line (R3).

    Format: icon <b>kind</b> · service · <code>fp</code> [× N]
    Counter omitted when count == 1 (R8).
    """
    fp_safe = escape_html(fingerprint)
    service_safe = escape_html(service)
    counter = f" × {count}" if count >= 2 else ""
    header = f"{icon} <b>{kind_label}</b> · {service_safe} · <code>{fp_safe}</code>{counter}"
    return f"{header}\n{SEPARATOR}"


def _mono_to_wall(mono: float) -> float:
    """Convert monotonic timestamp to wall-clock (best-effort approximation)."""
    return time.time() - (time.monotonic() - mono)


def _render_details(
    *,
    ts: float,
    pid: int,
    count: int,
    first_seen: float,
    last_seen: float,
    extra_lines: list[str],
) -> str:
    """Choose single-time or first/last Details block (R9)."""
    if count > 1:
        lines = [
            f"  first    {_fmt_utc(_mono_to_wall(first_seen))}",
            f"  last     {_fmt_utc(_mono_to_wall(last_seen))}",
            f"  pid      {pid}",
        ]
    else:
        lines = [
            f"  time     {_fmt_utc(ts)}",
            f"  pid      {pid}",
        ]
    lines.extend(extra_lines)
    return "<b>Details</b>\n" + "\n".join(lines)


def _render_context(context: dict[str, Any] | None) -> str | None:
    """Render the Context block. Returns None if context is empty/None (R10)."""
    if not context:
        return None

    items = list(context.items())
    shown = items[:_MAX_CONTEXT_ENTRIES]
    remaining = len(items) - len(shown)

    lines = []
    for k, v in shown:
        k_safe = escape_html(str(k))
        v_safe = escape_html(str(v))
        lines.append(f"  {k_safe}  {v_safe}")
    if remaining > 0:
        lines.append(f"  ... {remaining} more")

    return "<b>Context</b>\n" + "\n".join(lines)


def _render_stack_frames(frames: list[dict]) -> str:
    """Render up to 3 user frames in a <pre> block.

    Spec §4.1: '<b>Stack</b> (top 3 user frames)' — parenthetical outside bold.
    """
    user_frames = [f for f in frames if f.get("is_user_code")]
    no_user = False
    if not user_frames:
        user_frames = frames
        no_user = True

    shown = user_frames[:_MAX_STACK_FRAMES]
    frame_lines = []
    for f in shown:
        file_safe = escape_html(f.get("file", ""))
        func_safe = escape_html(f.get("func", ""))
        line_no = f.get("line", 0)
        frame_lines.append(f"{file_safe}:{line_no} in {func_safe}()")
        code = f.get("code")
        if code:
            frame_lines.append(f"  {escape_html(code)}")

    suffix = " (no user frames)" if no_user else " (top 3 user frames)"
    header = f"<b>Stack</b>{suffix}"
    return header + "\n<pre>\n" + "\n".join(frame_lines) + "\n</pre>"


def _custom_kind_label(payload: dict, event: dict) -> str:
    """Derive kind_label for custom events based on source.

    - source="logging"   -> "log.warning" / "log.error" / "log.critical"
    - source="structlog" -> "log.warning" / "log.error" / "log.critical"
    - source="exception" -> "exception"
    - otherwise          -> "notify"
    """
    source = payload.get("source")
    if source in ("logging", "structlog"):
        severity = event.get("severity", "warning")
        return f"log.{severity}"
    if source == "exception":
        return "exception"
    return "notify"
