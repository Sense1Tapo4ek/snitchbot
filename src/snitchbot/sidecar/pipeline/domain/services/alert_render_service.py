"""Alert render service.

Pure domain service. No I/O, no frameworks. Stdlib only.

Renders a telemetry event + dedup entry into an HTML string suitable
for Telegram's HTML parse_mode. Pure function — no side effects.
"""
from .renderers import (
    render_anomaly,
    render_crash,
    render_custom,
    render_slow_call,
    render_watchdog,
)

__all__ = ["render_alert"]

_KIND_RENDERERS = {
    "crash": render_crash,
    "custom": render_custom,
    "slow_call": render_slow_call,
    "watchdog": render_watchdog,
    "anomaly": render_anomaly,
}

def render_alert(*, event: dict, dedup_entry: dict, service: str) -> str:
    """Render an alert message as HTML for Telegram.

    Invariants:
    - R1: HTML parse_mode always (result contains HTML tags).
    - R2: severity icon consistent (from severity_icon_service).
    - R3: header = icon · kind · service · <code>fp</code> [× N].
    - R4: trace button only when stack is available.
    - R8: counter omitted when count == 1.
    - R9: first/last timestamps shown only when count > 1.
    - R10: Context block hidden when empty/None.
    - R11: HTML escape on all user-supplied values.
    - R12: severity_upgrade -> caller renders new message with new icon
           (this function uses dedup_entry.severity, so upgraded entries
            naturally render with the new icon).

    ``dedup_entry`` is a dict with keys: count, first_seen, last_seen,
    severity, message_id. severity is used for the icon (R12).
    """
    kind = event.get("kind", "")
    renderer = _KIND_RENDERERS.get(kind)
    if renderer is None:
        raise ValueError(f"Unknown event kind for alert render: {kind!r}")
    return renderer(event, dedup_entry, service)
