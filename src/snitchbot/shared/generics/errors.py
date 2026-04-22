"""Shared error hierarchy for the snitchbot telemetry library.

Matches the S-DDD error pattern (see ~/.claude/rules/s-ddd_python/errors.md):

    Exception
    └── LayerError
        ├── DomainError   — raised in domain/
        ├── AppError      — raised in app/
        ├── PortError     — raised in ports/
        └── AdapterError  — raised in adapters/

All exceptions use the classic ``__init__`` + ``super().__init__(msg)`` pattern.
Concrete semantic errors (e.g. ``EventOversizedError``) live next to the
bounded context they belong to, not in this module.
"""


class LayerError(Exception):
    """Base class for all application-logic errors across every layer."""


class DomainError(LayerError):
    """Business-rule violation. Raised in ``domain/``."""


class AppError(LayerError):
    """Orchestration failure. Raised in ``app/``."""


class PortError(LayerError):
    """Boundary / infrastructure failure. Raised in ``ports/``."""


class AdapterError(LayerError):
    """Framework or I/O failure. Raised in ``adapters/``."""


class TgRateLimitError(PortError):
    """429 Too Many Requests from Telegram Bot API. Invariant RL6.

    Placed in shared so pipeline/app can catch it without crossing
    the telegram_io sibling boundary.
    """

    def __init__(self, retry_after_sec: float) -> None:
        self.retry_after_sec = retry_after_sec
        super().__init__(f"429 Too Many Requests, retry after {retry_after_sec}s")
