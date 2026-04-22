"""Domain-specific semantic errors for the shared kernel.

Every class here inherits from :class:`snitchbot.shared.generics.errors.DomainError`
and follows the classic ``__init__`` + ``super().__init__(msg)`` pattern
(no dataclass exceptions — see ~/.claude/rules/s-ddd_python/errors.md).

Additional domain errors will be added here as subsequent tasks land
(``EventValidationError``, ``EventOversizedError``, ``UnknownKindError``,
``BadVersionError`` — per plan Task 1.1/1.2/1.3).
"""

from snitchbot.shared.generics.errors import DomainError


class InvalidAnomalyConfigError(DomainError):
    """Raised when an anomaly-detection config field is out of valid range.

    See vitals-design §4.6 (invariant A8) and public-api §3.5. Clients must
    validate the config before sending ``hello`` to the sidecar; the sidecar
    trusts the pre-validated canonical form it receives.
    """

    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class EventValidationError(DomainError):
    """Raised when an event fails client-side validation.

    Spec: ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §8 and
    invariant E5. The validation service returns a list of error strings; this
    exception aggregates them for callers that prefer the raise-style API.
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors: list[str] = list(errors) if errors else []
        super().__init__(message)


class EventOversizedError(DomainError):
    """Raised when an event exceeds the 8 KB msgpack size limit.

    Spec §7 / invariant E4. After progressive truncation fails to bring the
    event under the limit, the client drops it and increments
    ``stats.oversized``.
    """

    def __init__(self, event_size: int) -> None:
        self.event_size = event_size
        super().__init__(f"Event size {event_size} bytes exceeds 8 KB limit")


class UnknownKindError(DomainError):
    """Raised when an event kind is not one of the six known kinds.

    Spec §3 / §8. The known-kinds set is closed — see
    :data:`snitchbot.shared.domain.event_kind_vo.EventKind`.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Unknown event kind: {kind!r}")


class BadVersionError(DomainError):
    """Raised when the envelope protocol version is not the expected value.

    Spec §10 / invariant E5. In MVP the client checks ``v == 1`` strictly.
    """

    def __init__(self, version: int) -> None:
        self.version = version
        super().__init__(f"Bad event protocol version: {version!r} (expected 1)")
