"""Window parser and command argument parser.

Pure domain, stdlib only.

"""
import re

__all__ = ["parse_window", "parse_command_args"]

# Bounds: 1 minute to 30 days (inclusive)
_MIN_WINDOW_SEC = 60          # 1m
_MAX_WINDOW_SEC = 30 * 86400  # 30d

_WINDOW_RE = re.compile(r"^(\d+)(m|h|d)$")

_MULTIPLIERS = {"m": 60, "h": 3600, "d": 86400}

# Stateful commands whose rate-limited message must say "not processed"
_STATEFUL_COMMANDS = frozenset({"mute", "unmute"})

# Default values per command (spec §4.2, §5.2)
_LAST_DEFAULT_N = 5
_LAST_MAX_N = 20
_DEFAULT_WINDOW_SEC = 3600  # 1h

# Valid fingerprint: 6 hex chars
_FP_RE = re.compile(r"^[0-9a-f]{6}$")

def parse_window(s: str) -> int:
    """Parse a window string into seconds.

    Accepts: Nm (1–59), Nh (1–23), Nd (1–30).
    Bounds: 1m..30d.

    Args:
        s: Window string like '5m', '1h', '24h', '7d'.

    Returns:
        Number of seconds.

    Raises:
        ValueError: If the format is invalid or the value is out of range.
    """
    m = _WINDOW_RE.match(s.strip())
    if not m:
        raise ValueError(
            f"invalid window format '{s}' — use Nm / Nh / Nd (e.g. 5m, 1h, 7d)"
        )

    value = int(m.group(1))
    unit = m.group(2)
    seconds = value * _MULTIPLIERS[unit]

    if seconds < _MIN_WINDOW_SEC or seconds > _MAX_WINDOW_SEC:
        raise ValueError(
            f"window '{s}' is out of range [1m, 30d]"
        )
    return seconds

def _is_window_token(token: str) -> bool:
    """Return True if token looks like a window string."""
    return bool(_WINDOW_RE.match(token))

def _is_int_token(token: str) -> bool:
    """Return True if token is a non-negative integer."""
    return token.isdigit()

def parse_command_args(text: str, command: str) -> dict:
    """Parse command text into a typed argument dict.

    Supports: status, last, mute, unmute.
    Ignores leading '/' and command name in text.

    Args:
        text: Full message text, e.g. '/last 10 1h all'.
        command: Command name without slash, e.g. 'last'.

    Returns:
        Dict with command-specific keys.

    Raises:
        ValueError: If required arguments are missing or invalid.
    """
    # Strip command prefix
    stripped = text.strip()
    # Remove leading slash + command word
    prefix = f"/{command}"
    if stripped.startswith(prefix):
        remainder = stripped[len(prefix):].strip()
    else:
        remainder = stripped

    tokens = remainder.split() if remainder else []

    if command == "status":
        return _parse_status(tokens)
    if command == "last":
        return _parse_last(tokens)
    if command == "mute":
        return _parse_mute(tokens)
    if command == "unmute":
        return _parse_unmute(tokens)

    raise ValueError(f"Unknown command: {command}")

def _parse_status(tokens: list[str]) -> dict:
    """Parse /status [window] args."""
    window_sec = _DEFAULT_WINDOW_SEC
    for token in tokens:
        if _is_window_token(token):
            window_sec = parse_window(token)
        else:
            raise ValueError(
                f"invalid /status argument '{token}' — use /status [5m|1h|24h|7d|...]"
            )
    return {"window_sec": window_sec}

def _parse_last(tokens: list[str]) -> dict:
    """Parse /last [N] [window] [all] in any order."""
    n = _LAST_DEFAULT_N
    window_sec = _DEFAULT_WINDOW_SEC
    include_warnings = False

    for token in tokens:
        if token == "all":
            include_warnings = True
        elif _is_window_token(token):
            window_sec = parse_window(token)
        elif _is_int_token(token):
            requested = int(token)
            n = min(requested, _LAST_MAX_N)
        else:
            raise ValueError(
                f"invalid /last argument '{token}' — use /last [N] [window] [all]"
            )

    return {"n": n, "window_sec": window_sec, "include_warnings": include_warnings}

def _parse_mute(tokens: list[str]) -> dict:
    """Parse /mute <fp|all> <duration>."""
    if len(tokens) < 2:
        raise ValueError(
            "usage: /mute <fingerprint|all> <duration> (e.g. /mute a1b2c3 1h)"
        )

    fingerprint = tokens[0]
    duration_token = tokens[1]

    if fingerprint != "all" and not _FP_RE.match(fingerprint):
        raise ValueError(
            f"invalid fingerprint '{fingerprint}' — expect 6 hex chars or 'all'"
        )

    if not _is_window_token(duration_token):
        raise ValueError(
            f"invalid duration '{duration_token}' — use 5m/1h/24h/7d"
        )
    duration_sec = parse_window(duration_token)

    return {"fingerprint": fingerprint, "duration_sec": duration_sec}

def _parse_unmute(tokens: list[str]) -> dict:
    """Parse /unmute <fp|all>."""
    if len(tokens) < 1:
        raise ValueError(
            "usage: /unmute <fingerprint|all>"
        )

    fingerprint = tokens[0]
    if fingerprint != "all" and not _FP_RE.match(fingerprint):
        raise ValueError(
            f"invalid fingerprint '{fingerprint}' — expect 6 hex chars or 'all'"
        )

    return {"fingerprint": fingerprint}
