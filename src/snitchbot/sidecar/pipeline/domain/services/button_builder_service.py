"""Inline keyboard button builder for Telegram alert messages.

Invariants:
  R4  — trace button only when stack/trace is available.
  T12 — callback data format: mute:<fp>:<dur>, trace:<fp>, unmute:<fp>.

Telegram InlineKeyboardButton schema: {"text": str, "callback_data": str}
Constraint: callback_data must be < 64 bytes (Telegram API limit).
"""
# Mute durations exposed as inline buttons.
# Values are the callback_data duration tokens and must be concise to keep
# callback_data under 64 bytes even with a 6-char fingerprint.
_MUTE_DURATIONS: tuple[tuple[str, str], ...] = (
    ("🔇 5m", "5m"),
    ("🔇 1h", "1h"),
    ("🔇 24h", "24h"),
)

def build_buttons(
    *,
    fingerprint: str,
    has_trace: bool,
) -> list[list[dict]]:
    """Build the inline keyboard for an alert message.

    Always produces one row with 3 mute buttons.
    Adds a 4th [📋 Trace] button when has_trace is True (R4).

    Args:
        fingerprint: 6-char hex fingerprint of the alert.
        has_trace:   True when the event payload contains a stack/trace.

    Returns:
        One-element list (single keyboard row) of InlineKeyboardButton dicts.
        Each dict has "text" and "callback_data" keys.
        All callback_data values are < 64 bytes.
    """
    row: list[dict] = []

    for label, duration_token in _MUTE_DURATIONS:
        callback_data = f"mute:{fingerprint}:{duration_token}"
        row.append({"text": label, "callback_data": callback_data})

    if has_trace:
        row.append({"text": "📋 Trace", "callback_data": f"trace:{fingerprint}"})

    return [row]

__all__ = ["build_buttons"]
