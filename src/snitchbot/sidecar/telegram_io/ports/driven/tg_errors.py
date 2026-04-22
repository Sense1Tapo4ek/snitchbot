"""Telegram-specific port errors.

All errors inherit from PortError (see shared/generics/errors.py).
Classic __init__ + super().__init__(msg) pattern — no @dataclass.

TgRateLimitError is re-exported from shared.generics.errors so that
sibling contexts (e.g. pipeline) can catch it without crossing the
telegram_io boundary.
"""

from snitchbot.shared.generics.errors import PortError, TgRateLimitError

__all__ = [
    "TgRateLimitError",
    "TgNetworkError",
    "TgApiError",
    "TgPermissionError",
    "TgThreadNotFoundError",
]


class TgNetworkError(PortError):
    """Network or timeout failure talking to Telegram Bot API."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class TgApiError(PortError):
    """Non-200, non-429 response from Telegram Bot API."""

    def __init__(self, status_code: int, description: str) -> None:
        self.status_code = status_code
        self.description = description
        super().__init__(f"Telegram API error {status_code}: {description}")


class TgPermissionError(TgApiError):
    """Bot lacks the right to perform this action (e.g., can_manage_topics)."""

    def __init__(self, description: str = "permission denied") -> None:
        super().__init__(403, description)


class TgThreadNotFoundError(TgApiError):
    """`message thread not found` — topic was deleted or never existed."""

    def __init__(self, description: str = "message thread not found") -> None:
        super().__init__(400, description)
