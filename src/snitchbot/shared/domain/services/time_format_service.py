"""Shared time formatting utilities.

Pure functions, stdlib only. Used across multiple bounded contexts.
"""
from datetime import datetime, timezone


def fmt_utc(ts: float) -> str:
    """Format a Unix timestamp as 'YYYY-MM-DD HH:MM:SS UTC'."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_window_label(sec: float) -> str:
    """Format a duration in seconds as a compact label (e.g. '5m', '1h', '7d')."""
    if sec <= 0:
        return "0s"
    if sec % 86400 == 0:
        return f"{int(sec // 86400)}d"
    if sec % 3600 == 0:
        return f"{int(sec // 3600)}h"
    if sec >= 60:
        return f"{int(sec // 60)}m"
    return f"{int(sec)}s"


def fmt_uptime(seconds: float) -> str:
    """Format elapsed seconds as 'Xh Ym'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"
