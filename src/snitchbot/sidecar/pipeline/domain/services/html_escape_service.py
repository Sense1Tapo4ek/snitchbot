"""HTML escape service for Telegram HTML parse_mode.

Pure domain service. No I/O, no frameworks. Stdlib only.

Telegram HTML parse_mode requires escaping &, <, > in user-supplied text.
No other characters need escaping (Telegram subset only supports
<b>, <i>, <code>, <pre>, <a> — no attribute values from user data).
"""
__all__ = ["escape_html"]

def escape_html(text: str) -> str:
    """Escape &, <, > for Telegram HTML parse_mode (R11).

    Order matters: & must be replaced first to avoid double-escaping.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
