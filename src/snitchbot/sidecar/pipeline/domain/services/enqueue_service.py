"""Shared event enqueue logic — classify, prioritize, and enqueue.

Used by both recv_loop (client events) and anomaly workflow (internal events).
"""
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache

__all__ = ["ACTION_TO_PRIORITY", "classify_and_enqueue"]

ACTION_TO_PRIORITY: dict[str, QueuePriority] = {
    "new_alert": QueuePriority.NEW_ALERT,
    "counter_edit": QueuePriority.COUNTER_EDIT,
    "severity_upgrade": QueuePriority.SEVERITY_UPGRADE,
    "lifecycle_bypass": QueuePriority.NEW_ALERT,
}


def classify_and_enqueue(
    *,
    event: dict,
    fingerprint: str | None,
    dedup: DedupCache,
    queue: CentralQueue,
    now: float,
) -> tuple[bool, str, dict]:
    """Classify via dedup, determine priority, enqueue.

    Returns (accepted, action, enriched_event).
    """
    action = dedup.classify(
        fingerprint=fingerprint,
        severity=event.get("severity"),
        event=event,
        now=now,
    )
    enriched = {**event, "fingerprint": fingerprint, "action": action}

    priority = ACTION_TO_PRIORITY.get(action, QueuePriority.NEW_ALERT)
    if event.get("severity") == "critical":
        priority = QueuePriority.CRITICAL

    accepted = queue.enqueue(QueueItem(priority=priority, payload=enriched))
    return accepted, action, enriched
