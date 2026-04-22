"""Unit tests for CentralQueue — Task 6.1.

Invariants validated: RL4, RL5.
"""
import time

from snitchbot.shared.constants import QUEUE_MAX
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(priority: QueuePriority, tag: str = "") -> QueueItem:
    return QueueItem(priority=priority, payload={"tag": tag}, enqueued_at=time.monotonic())


# ---------------------------------------------------------------------------
# test_queue_max_256
# ---------------------------------------------------------------------------

def test_queue_max_256():
    """QUEUE_MAX constant is 256 and CentralQueue defaults to that size."""
    assert QUEUE_MAX == 256
    q = CentralQueue()
    # fill to max
    for i in range(QUEUE_MAX):
        accepted = q.enqueue(_item(QueuePriority.NEW_ALERT, str(i)))
        assert accepted is True
    assert len(q) == QUEUE_MAX


# ---------------------------------------------------------------------------
# test_drop_oldest_when_full  (RL5)
# ---------------------------------------------------------------------------

def test_drop_oldest_when_full():
    """
    When the queue is full and a new non-critical item arrives,
    the oldest non-critical item is dropped.
    RL5: drop-oldest for non-critical overflow.
    """
    q = CentralQueue(max_size=4)
    # enqueue items with distinct tags to identify them later
    for i in range(4):
        q.enqueue(_item(QueuePriority.NEW_ALERT, f"old-{i}"))
    assert len(q) == 4

    # enqueue one more; the oldest ("old-0") should be evicted
    accepted = q.enqueue(_item(QueuePriority.NEW_ALERT, "new"))
    assert accepted is True
    assert len(q) == 4

    # dequeue all; "old-0" must not be present
    tags = []
    while True:
        item = q.dequeue()
        if item is None:
            break
        tags.append(item.payload["tag"])

    assert "old-0" not in tags
    assert "new" in tags


# ---------------------------------------------------------------------------
# test_critical_not_evicted_pushes_next_oldest  (RL5)
# ---------------------------------------------------------------------------

def test_critical_not_evicted_pushes_next_oldest():
    """
    RL5: critical items cannot be evicted.
    When the oldest item is critical, the eviction skips it and drops
    the next oldest non-critical item instead.
    """
    q = CentralQueue(max_size=3)

    # First item: critical (oldest)
    q.enqueue(_item(QueuePriority.CRITICAL, "crit-first"))
    # Second and third: non-critical
    q.enqueue(_item(QueuePriority.NEW_ALERT, "non-crit-1"))
    q.enqueue(_item(QueuePriority.COUNTER_EDIT, "non-crit-2"))
    assert len(q) == 3

    # Overflow: queue is full, enqueue a new non-critical item.
    # "non-crit-1" is the oldest non-critical -> gets evicted, not "crit-first".
    accepted = q.enqueue(_item(QueuePriority.NEW_ALERT, "new-item"))
    assert accepted is True
    assert len(q) == 3

    tags = []
    while True:
        item = q.dequeue()
        if item is None:
            break
        tags.append(item.payload["tag"])

    assert "crit-first" in tags
    assert "non-crit-1" not in tags
    assert "new-item" in tags


# ---------------------------------------------------------------------------
# test_all_critical_queue_drops_new_noncritical
# ---------------------------------------------------------------------------

def test_all_critical_queue_drops_new_noncritical():
    """
    When every slot is occupied by a critical item, a new non-critical item
    is silently dropped (enqueue returns False).
    """
    q = CentralQueue(max_size=3)
    for i in range(3):
        q.enqueue(_item(QueuePriority.CRITICAL, f"c{i}"))
    assert len(q) == 3

    accepted = q.enqueue(_item(QueuePriority.NEW_ALERT, "dropped"))
    assert accepted is False
    assert len(q) == 3  # queue unchanged


# ---------------------------------------------------------------------------
# test_priority_comparator_class_ordering
# ---------------------------------------------------------------------------

def test_priority_comparator_class_ordering():
    """
    Priority enum ordering: lower value = higher priority = dequeued first.
    CRITICAL(0) < TEST_RESPONSE(1) < SEVERITY_UPGRADE(2) < NEW_ALERT(3)
    < COUNTER_EDIT(4) < LIVE_EDIT(5) < COMMAND_RESPONSE(6).
    """
    assert QueuePriority.CRITICAL < QueuePriority.TEST_RESPONSE
    assert QueuePriority.TEST_RESPONSE < QueuePriority.SEVERITY_UPGRADE
    assert QueuePriority.SEVERITY_UPGRADE < QueuePriority.NEW_ALERT
    assert QueuePriority.NEW_ALERT < QueuePriority.COUNTER_EDIT
    assert QueuePriority.COUNTER_EDIT < QueuePriority.LIVE_EDIT
    assert QueuePriority.LIVE_EDIT < QueuePriority.COMMAND_RESPONSE


# ---------------------------------------------------------------------------
# test_counter_edits_dropped_before_new_alerts_under_pressure  (RL4)
# ---------------------------------------------------------------------------

def test_counter_edits_dropped_before_new_alerts_under_pressure():
    """
    RL4: under overflow pressure, counter edits are evicted before new alerts.
    Queue full of counter_edits; add a new_alert -> oldest counter_edit drops.
    """
    q = CentralQueue(max_size=3)
    for i in range(3):
        q.enqueue(_item(QueuePriority.COUNTER_EDIT, f"edit-{i}"))

    accepted = q.enqueue(_item(QueuePriority.NEW_ALERT, "fresh-alert"))
    assert accepted is True

    tags = []
    while True:
        item = q.dequeue()
        if item is None:
            break
        tags.append(item.payload["tag"])

    assert "fresh-alert" in tags
    assert "edit-0" not in tags  # oldest counter_edit evicted


# ---------------------------------------------------------------------------
# test_fifo_within_same_priority_class
# ---------------------------------------------------------------------------

def test_fifo_within_same_priority_class():
    """
    Items with the same priority are dequeued in FIFO (insertion) order.
    """
    q = CentralQueue(max_size=10)
    for i in range(5):
        q.enqueue(_item(QueuePriority.NEW_ALERT, f"item-{i}"))

    order = []
    while True:
        item = q.dequeue()
        if item is None:
            break
        order.append(item.payload["tag"])

    assert order == ["item-0", "item-1", "item-2", "item-3", "item-4"]


# ---------------------------------------------------------------------------
# test_queue_depth_reported_for_status_block
# ---------------------------------------------------------------------------

def test_queue_depth_reported_for_status_block():
    """
    CentralQueue.depth reports the current number of items,
    matching len(queue) and matching the spec §6 status block.
    """
    q = CentralQueue(max_size=10)
    assert q.depth == 0
    assert len(q) == 0

    q.enqueue(_item(QueuePriority.NEW_ALERT))
    q.enqueue(_item(QueuePriority.CRITICAL))
    assert q.depth == 2
    assert len(q) == 2

    q.dequeue()
    assert q.depth == 1
    assert len(q) == 1
