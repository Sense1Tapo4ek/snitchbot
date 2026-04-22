"""Periodic edit flusher workflow (D4).

Pure computation — stdlib only. No I/O, no frameworks.
"""
from dataclasses import dataclass

from snitchbot.sidecar.pipeline.domain.central_queue_agg import QueueItem, QueuePriority
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache

@dataclass(frozen=True, slots=True, kw_only=True)
class EditFlusherWorkflow:
    """Periodic flusher that dispatches pending edits (D4).

    Ticks every 2s (configurable by caller).
    Each fingerprint is throttled to max 1 edit per 5s.
    Single processing path — no immediate edits on event arrival.
    """

    _dedup_cache: DedupCache
    _min_edit_interval_sec: float = 5.0

    def tick(self, now: float) -> list[QueueItem]:
        """Scan dedup cache for pending edits.

        For each entry with pending_edit=True:
        - If now - entry.last_edit_at >= min_edit_interval_sec -> dispatch,
          clear flag, update last_edit_at.
        - Else -> skip (throttled).

        Args:
            now: monotonic timestamp injected for deterministic testing.

        Returns:
            List of QueueItem(COUNTER_EDIT), one per dispatched fingerprint.
        """
        items: list[QueueItem] = []
        for fp, entry in self._dedup_cache.entries():
            if not entry.pending_edit:
                continue
            if now - entry.last_edit_at < self._min_edit_interval_sec:
                continue
            event = entry.latest_event or {}
            payload = {
                **event,
                "fingerprint": fp,
                "action": "counter_edit",
                "event": event,
                "count": entry.count,
                "severity": entry.severity,
                "message_id": entry.message_id,
            }
            items.append(QueueItem(priority=QueuePriority.COUNTER_EDIT, payload=payload))
            self._dedup_cache.mark_dispatched(fp, now)
        return items
