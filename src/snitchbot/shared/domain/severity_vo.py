"""Severity value object for the snitchbot telemetry event model.

Severity is a closed set of three literal strings: ``warning``, ``error``,
``critical``. The ``lifecycle`` event kind carries ``severity=None`` and is
NOT passed through :func:`severity_rank` — lifecycle events bypass the
alert pipeline entirely (see §4.6 and §5 of the spec).
"""
from typing import Literal

from snitchbot.shared.generics.errors import DomainError

Severity = Literal["warning", "error", "critical"]

_RANKS: dict[str, int] = {
    "warning": 1,
    "error": 2,
    "critical": 3,
}

class InvalidSeverityError(DomainError):
    """Raised when a value outside {warning, error, critical} is used as severity."""

    def __init__(self, value: object) -> None:
        self.value = value
        super().__init__(
            f"Invalid severity {value!r}: expected one of 'warning', 'error', 'critical'"
        )

def severity_rank(sev: Severity) -> int:
    """Return the ordinal rank of a severity: 1=warning, 2=error, 3=critical.

    Lifecycle events (``severity=None``) do not participate in ranking and
    must not be passed here — pass only the three literal severity values.

    Raises:
        InvalidSeverityError: if ``sev`` is not one of the three allowed literals.
    """
    try:
        return _RANKS[sev]
    except (KeyError, TypeError) as exc:
        raise InvalidSeverityError(sev) from exc
