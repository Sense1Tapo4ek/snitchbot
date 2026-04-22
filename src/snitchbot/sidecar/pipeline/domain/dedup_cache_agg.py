"""Byte-capped LRU deduplication cache for the sidecar alert pipeline.

Pure domain: stdlib only. No frameworks, no I/O.
"""
import sys
from dataclasses import dataclass

from snitchbot.shared.constants import (
    DEDUP_CACHE_MAX_BYTES,
    DEDUP_CACHE_MAX_ENTRIES,
    DEDUP_WINDOW_SEC,
)
from snitchbot.shared.domain import severity_rank

@dataclass(slots=True)
class DedupEntry:
    """Tracks a deduplicated event group by fingerprint."""

    fingerprint: str
    first_seen: float
    last_seen: float
    count: int
    severity: str
    latest_event: dict
    message_id: int | None  # TG message ID for edits
    last_edit_at: float
    pending_edit: bool
    byte_size: int  # estimated size for byte cap

def _estimate_bytes(fingerprint: str, event: dict) -> int:
    """Rough byte estimate for a DedupEntry: fixed overhead + event size.

    Uses ``sys.getsizeof(str(event))`` rather than ``sys.getsizeof(msgpack.packb(event))``.
    str() produces a larger representation than msgpack binary, so this is a conservative
    *overestimate*: entries are evicted from the cache slightly sooner than necessary.
    That is the SAFER direction — it keeps memory usage below the cap rather than over it.
    Importing msgpack here would violate the S-DDD rule (domain = stdlib only), so the
    overestimate is intentional and acceptable.  See spec D5 for the byte-cap invariant.
    """
    fixed = 150  # DedupEntry fixed fields
    try:
        event_size = sys.getsizeof(str(event))
    except Exception:
        event_size = 256
    return fixed + event_size

class DedupCache:
    """Dedup cache with configurable window, byte cap, and entry cap.

    Defaults match spec constants:
    - window_sec=300  (D1, DEDUP_WINDOW_SEC)
    - max_bytes=10 MiB  (D5, DEDUP_CACHE_MAX_BYTES)
    - max_entries=10_000  (D5, DEDUP_CACHE_MAX_ENTRIES)

    Returns classification for each event:
    - "new_alert":        first time seeing this fingerprint (or window expired)
    - "counter_edit":     same fingerprint within window, counter bumped
    - "severity_upgrade": same fp but higher severity -> new alert (D3)
    - "lifecycle_bypass": fingerprint is None -> lifecycle event bypasses dedup (D7)
    """

    def __init__(
        self,
        window_sec: int = DEDUP_WINDOW_SEC,
        max_bytes: int = DEDUP_CACHE_MAX_BYTES,
        max_entries: int = DEDUP_CACHE_MAX_ENTRIES,
    ) -> None:
        self._entries: dict[str, DedupEntry] = {}
        self._window_sec = window_sec
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._total_bytes = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        *,
        fingerprint: str | None,
        severity: str | None,
        event: dict,
        now: float,
    ) -> str:
        """Classify incoming event. Returns action string.

        Args:
            fingerprint: event fingerprint; None for lifecycle events (D7).
            severity: event severity string; None for lifecycle events.
            event: raw event dict (stored as latest_event).
            now: monotonic timestamp injected for deterministic testing.

        Returns:
            One of: "lifecycle_bypass", "new_alert", "severity_upgrade", "counter_edit".
        """
        if fingerprint is None:
            return "lifecycle_bypass"  # D7

        entry = self._entries.get(fingerprint)

        if entry is None or (now - entry.last_seen) > self._window_sec:
            # New or expired -> create/reset, return new_alert
            self._create_or_reset(fingerprint, severity, event, now)
            return "new_alert"

        # Hot entry (within window)
        if self._is_upgrade(entry.severity, severity):
            # D3: severity upgrade -> treat as new alert, update severity
            entry.severity = severity  # type: ignore[assignment]
            entry.count += 1
            entry.last_seen = now
            entry.latest_event = event
            # Update byte size
            new_size = _estimate_bytes(fingerprint, event)
            self._total_bytes += new_size - entry.byte_size
            entry.byte_size = new_size
            return "severity_upgrade"

        # Same or lower severity -> counter bump
        entry.count += 1
        entry.last_seen = now
        entry.latest_event = event
        entry.pending_edit = True
        # Update byte size
        new_size = _estimate_bytes(fingerprint, event)
        self._total_bytes += new_size - entry.byte_size
        entry.byte_size = new_size
        return "counter_edit"

    def evict_if_over_cap(self) -> int:
        """Evict LRU entries until under byte and entry caps.

        Removes entries with oldest last_seen first until both:
        - total_bytes <= 90% of max_bytes
        - len(entries) <= max_entries

        Returns:
            Number of entries evicted.
        """
        target_bytes = int(self._max_bytes * 0.9)
        evicted = 0

        while self._entries and (
            self._total_bytes > target_bytes
            or len(self._entries) > self._max_entries
        ):
            # Find LRU entry (smallest last_seen)
            lru_fp = min(self._entries, key=lambda fp: self._entries[fp].last_seen)
            removed = self._entries.pop(lru_fp)
            self._total_bytes -= removed.byte_size
            evicted += 1

        return evicted

    def gc(self, now: float) -> int:
        """Remove entries older than 2x window (background GC).

        Spec D6: entries where now - last_seen > 2 * DEDUP_WINDOW_SEC are stale.

        Returns:
            Number of entries removed.
        """
        cutoff = 2 * self._window_sec
        stale = [fp for fp, e in self._entries.items() if (now - e.last_seen) > cutoff]
        for fp in stale:
            removed = self._entries.pop(fp)
            self._total_bytes -= removed.byte_size
        return len(stale)

    def entries(self):
        """Iterate over (fingerprint, DedupEntry) pairs.

        Returns a view of the internal entries dict items.
        Used by EditFlusherWorkflow to scan for pending edits.
        """
        return self._entries.items()

    def get_entry(self, fingerprint: str) -> DedupEntry | None:
        """Return the DedupEntry for fingerprint, or None if not found."""
        return self._entries.get(fingerprint)

    def mark_dispatched(self, fingerprint: str, now: float) -> None:
        """Clear pending_edit flag and record dispatch time for a fingerprint."""
        entry = self._entries.get(fingerprint)
        if entry:
            entry.pending_edit = False
            entry.last_edit_at = now

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_or_reset(
        self, fingerprint: str, severity: str | None, event: dict, now: float
    ) -> None:
        """Insert or overwrite an entry for fingerprint."""
        byte_size = _estimate_bytes(fingerprint, event)

        # If replacing an existing entry, subtract its old size first
        if fingerprint in self._entries:
            self._total_bytes -= self._entries[fingerprint].byte_size

        entry = DedupEntry(
            fingerprint=fingerprint,
            first_seen=now,
            last_seen=now,
            count=1,
            severity=severity or "warning",  # type: ignore[arg-type]
            latest_event=event,
            message_id=None,
            last_edit_at=0.0,
            pending_edit=False,
            byte_size=byte_size,
        )
        self._entries[fingerprint] = entry
        self._total_bytes += byte_size

    @staticmethod
    def _is_upgrade(current_severity: str, new_severity: str | None) -> bool:
        """Return True if new_severity ranks strictly higher than current (D3)."""
        if new_severity is None:
            return False
        try:
            return severity_rank(new_severity) > severity_rank(current_severity)  # type: ignore[arg-type]
        except Exception:
            return False
