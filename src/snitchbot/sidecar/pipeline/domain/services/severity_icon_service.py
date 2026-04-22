"""Severity icon service.

Pure domain service. No I/O, no frameworks. Stdlib only.

Three icons — one per severity level. Consistent across /last cards,
/mute records, and alert renders (R2).
"""
__all__ = ["severity_icon"]

_ICONS: dict[str, str] = {
    "warning": "🟠",
    "error": "🔴",
    "critical": "🟣",
}

def severity_icon(severity: str) -> str:
    """Return the Unicode circle icon for the given severity level (R2).

    warning -> 🟠, error -> 🔴, critical -> 🟣.
    Raises KeyError for unknown severity values.
    """
    return _ICONS[severity]
