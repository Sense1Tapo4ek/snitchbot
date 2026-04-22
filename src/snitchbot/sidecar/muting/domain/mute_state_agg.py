"""Sidecar domain: mute state aggregate.

Manages global and per-fingerprint mutes.
Pure Python stdlib — no frameworks, no I/O.

Invariants: T6 (critical never muted), T7/E9/D7 (lifecycle never muted),
            T9 (repeat mute rejected), §11.4 (suppressed_count not persisted).
"""
from dataclasses import dataclass

__all__ = ["MuteEntry", "MuteState"]


@dataclass(slots=True)
class MuteEntry:
    """A single active mute record.

    suppressed_count is intentionally mutable and NOT persisted (§11.4).

    ``service`` (F7): in forum mode a /mute issued inside a topic is scoped to
    that topic's service. ``None`` means the mute applies to all services
    (simple-mode behaviour, preserved for backward compat).
    """

    fingerprint: str | None  # None = global mute
    muted_at: float
    duration_sec: float
    source_message_id: int | None  # TG message that triggered mute (T11)
    exception_type: str | None = None  # §7.3: exception class name, if available
    suppressed_count: int = 0  # NOT persisted
    service: str | None = None  # F7: topic-scoped mute; None = applies to all

    @property
    def expires_at(self) -> float:
        return self.muted_at + self.duration_sec


class MuteState:
    """Manages active mutes.

    Critical events (severity='critical') are NEVER muted — T6, E8.
    Lifecycle events (fingerprint=None) are NEVER muted — T7, E9, D7.
    """

    def __init__(self) -> None:
        self._global: list[MuteEntry] = []  # zero/one global (None service) or multiple scoped globals
        self._per_fp: dict[tuple[str, str | None], MuteEntry] = {}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_muted(
        self,
        *,
        fingerprint: str | None,
        severity: str | None,
        now: float,
        service: str | None = None,
    ) -> bool:
        """Check if an event should be suppressed.

        Returns False (bypass) for:
        - severity == 'critical'  -> T6, E8
        - fingerprint is None     -> T7, E9, D7 (lifecycle events)

        Otherwise checks global mute, then per-fingerprint mute.
        Increments suppressed_count on the matching entry.

        ``service`` (F7): the event's service in forum mode. A mute entry's
        ``service`` field acts as a filter — ``None`` matches any event
        (simple-mode behaviour), a concrete value matches only events whose
        ``service`` equals it.
        """
        if severity == "critical":
            return False  # T6, E8

        if fingerprint is None:
            return False  # T7, E9, D7

        # Check global mute(s). Entry.service=None matches any service;
        # entry.service=X matches only events with event.service=X.
        for entry in self._global:
            if _is_expired(entry, now):
                continue
            if entry.service is not None and entry.service != service:
                continue
            entry.suppressed_count += 1
            return True

        # Check per-fingerprint mute. First try the service-scoped entry,
        # then the unscoped (None) entry.
        for key in ((fingerprint, service), (fingerprint, None)):
            entry = self._per_fp.get(key)
            if entry is not None and not _is_expired(entry, now):
                entry.suppressed_count += 1
                return True

        return False

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def mute(
        self,
        *,
        fingerprint: str | None,
        duration_sec: float,
        source_message_id: int | None,
        now: float,
        exception_type: str | None = None,
        service: str | None = None,
    ) -> bool:
        """Add a mute.

        Returns False if the target is already muted (T9).
        Expired entries are replaced (not considered 'already muted').

        ``service`` (F7): scope the mute to a single service (topic). ``None``
        means the mute applies to every service (simple-mode default).
        """
        if fingerprint is None:
            # Global mute — dedup by service scope
            for i, entry in enumerate(self._global):
                if entry.service == service and not _is_expired(entry, now):
                    return False  # T9
                if entry.service == service and _is_expired(entry, now):
                    # Replace expired entry
                    self._global[i] = MuteEntry(
                        fingerprint=None,
                        muted_at=now,
                        duration_sec=duration_sec,
                        source_message_id=source_message_id,
                        exception_type=exception_type,
                        service=service,
                    )
                    return True
            self._global.append(
                MuteEntry(
                    fingerprint=None,
                    muted_at=now,
                    duration_sec=duration_sec,
                    source_message_id=source_message_id,
                    exception_type=exception_type,
                    service=service,
                )
            )
            return True
        else:
            # Per-fingerprint mute, keyed by (fingerprint, service)
            key = (fingerprint, service)
            existing = self._per_fp.get(key)
            if existing is not None and not _is_expired(existing, now):
                return False  # T9
            self._per_fp[key] = MuteEntry(
                fingerprint=fingerprint,
                muted_at=now,
                duration_sec=duration_sec,
                source_message_id=source_message_id,
                exception_type=exception_type,
                service=service,
            )
            return True

    def unmute(
        self,
        *,
        fingerprint: str | None,
        service: str | None = None,
    ) -> bool:
        """Remove a mute.

        Returns False if no matching active mute exists.

        ``service`` (F7): drop only the entry scoped to that service. ``None``
        drops the global/unscoped entry (simple-mode default).
        """
        if fingerprint is None:
            for i, entry in enumerate(self._global):
                if entry.service == service:
                    del self._global[i]
                    return True
            return False
        else:
            key = (fingerprint, service)
            if key not in self._per_fp:
                return False
            del self._per_fp[key]
            return True

    def get_active_mutes(self, now: float) -> list[MuteEntry]:
        """Return list of non-expired mutes (for persistence and reporting)."""
        result: list[MuteEntry] = []

        for entry in self._global:
            if not _is_expired(entry, now):
                result.append(entry)

        for entry in self._per_fp.values():
            if not _is_expired(entry, now):
                result.append(entry)

        return result

    def get_entry(
        self,
        fingerprint: str | None,
        *,
        service: str | None = None,
    ) -> MuteEntry | None:
        """Return the active mute entry for a fingerprint, or the global entry
        (if ``fingerprint is None``).

        ``service``: in forum mode resolves the topic-scoped entry. ``None``
        returns the unscoped entry (simple-mode default).
        """
        if fingerprint is None:
            for entry in self._global:
                if entry.service == service:
                    return entry
            return None
        return self._per_fp.get((fingerprint, service))

    def active_count(self, now: float) -> int:
        """Return the number of non-expired mute entries at *now*."""
        count = 0
        for entry in self._global:
            if not _is_expired(entry, now):
                count += 1
        for entry in self._per_fp.values():
            if not _is_expired(entry, now):
                count += 1
        return count


def _is_expired(entry: MuteEntry, now: float) -> bool:
    return now >= entry.expires_at
