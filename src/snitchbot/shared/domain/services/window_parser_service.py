"""Window / duration parser — parses duration strings like 30s, 5m, 1h, 7d.

Pure domain: stdlib only.
"""
import re

__all__ = ["WindowParseError", "parse_window_seconds", "parse_duration"]

_PATTERN = re.compile(r"^(\d+)(m|h|d)$")
_DURATION_PATTERN = re.compile(r"^(\d+)\s*(s|m|h|d)$")

_LIMITS = {
    "m": (1, 59),
    "h": (1, 23),
    "d": (1, 7),
}

_MULTIPLIERS = {
    "m": 60,
    "h": 3600,
    "d": 86400,
}

class WindowParseError(ValueError):
    """Raised when a window string is malformed or out of range."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(f"Invalid window: {value!r}. Use Nm/Nh/Nd (e.g. 5m, 1h, 7d).")

def parse_window_seconds(value: str) -> float:
    """Parse a window string to seconds.

    Valid: 1m–59m, 1h–23h, 1d–7d.
    Raises WindowParseError on invalid input.
    """
    m = _PATTERN.match(value.strip())
    if not m:
        raise WindowParseError(value)

    amount = int(m.group(1))
    unit = m.group(2)
    lo, hi = _LIMITS[unit]

    if not (lo <= amount <= hi):
        raise WindowParseError(value)

    return float(amount * _MULTIPLIERS[unit])

# Duration parser for anomaly configs (supports seconds + int passthrough)

_DURATION_MULTIPLIERS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}

_MAX_DURATION_SEC = 172800  # 48 hours

def parse_duration(value: str | int) -> int:
    """Parse a duration string or int to seconds.

    Accepts:
    - ``int`` -> passthrough (interpreted as seconds).
    - ``"30s"`` -> 30
    - ``"2m"`` -> 120
    - ``"1h"`` -> 3600
    - ``"2d"`` -> 172800 (capped at 48h)

    Raises WindowParseError if malformed or out of range (0 < result <= 172800).
    """
    if isinstance(value, int):
        if value <= 0 or value > _MAX_DURATION_SEC:
            raise WindowParseError(str(value))
        return value

    if not isinstance(value, str):
        raise WindowParseError(repr(value))

    m = _DURATION_PATTERN.match(value.strip())
    if not m:
        raise WindowParseError(value)

    amount = int(m.group(1))
    unit = m.group(2)
    result = amount * _DURATION_MULTIPLIERS[unit]

    if result <= 0 or result > _MAX_DURATION_SEC:
        raise WindowParseError(value)

    return result
