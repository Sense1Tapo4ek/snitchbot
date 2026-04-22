"""Unit tests for DedupCache — byte-capped LRU deduplication cache.

Spec: docs/superpowers/specs/2026-04-11-dedup-rate-limit-design.md §3, D1–D7.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 6.2.
"""
import pytest

from snitchbot.shared.constants import (
    DEDUP_WINDOW_SEC,
)
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache, DedupEntry

# ---------------------------------------------------------------------------
# D1 — constant window
# ---------------------------------------------------------------------------


def test_dedup_window_300s_constant() -> None:
    """
    Given the module-level constant DEDUP_WINDOW_SEC,
    When inspected,
    Then it equals 300 seconds (spec D1).
    """
    assert DEDUP_WINDOW_SEC == 300


# ---------------------------------------------------------------------------
# new_alert path
# ---------------------------------------------------------------------------


def test_first_event_new_alert() -> None:
    """
    Given a fresh DedupCache,
    When classify() is called for a fingerprint never seen before,
    Then the result is 'new_alert' and an entry is created.
    """
    cache = DedupCache()
    result = cache.classify(
        fingerprint="fp-abc",
        severity="error",
        event={"kind": "error", "msg": "boom"},
        now=1000.0,
    )
    assert result == "new_alert"
    assert "fp-abc" in cache._entries


# ---------------------------------------------------------------------------
# counter_edit path
# ---------------------------------------------------------------------------


def test_same_fp_within_window_counter_edit() -> None:
    """
    Given a DedupCache with an existing entry,
    When classify() is called again within the dedup window,
    Then the result is 'counter_edit' and count is incremented.
    """
    cache = DedupCache()
    cache.classify(fingerprint="fp-x", severity="warning", event={"msg": "a"}, now=0.0)
    result = cache.classify(
        fingerprint="fp-x",
        severity="warning",
        event={"msg": "b"},
        now=100.0,  # well within 300 s window
    )
    assert result == "counter_edit"
    assert cache._entries["fp-x"].count == 2


# ---------------------------------------------------------------------------
# window expiry -> new_alert
# ---------------------------------------------------------------------------


def test_same_fp_after_window_new_alert() -> None:
    """
    Given an existing entry whose last_seen is more than DEDUP_WINDOW_SEC ago,
    When classify() is called,
    Then the result is 'new_alert' and the entry is reset.
    """
    cache = DedupCache()
    cache.classify(fingerprint="fp-y", severity="warning", event={"msg": "old"}, now=0.0)
    result = cache.classify(
        fingerprint="fp-y",
        severity="warning",
        event={"msg": "new"},
        now=301.0,  # one second past window
    )
    assert result == "new_alert"
    # Entry should be reset — count back to 1, first_seen updated
    entry = cache._entries["fp-y"]
    assert entry.count == 1
    assert entry.first_seen == pytest.approx(301.0)


# ---------------------------------------------------------------------------
# D3 — severity upgrade
# ---------------------------------------------------------------------------


def test_severity_upgrade_new_alert() -> None:
    """
    Given a hot entry with severity='warning',
    When a new event arrives with severity='error' (higher rank),
    Then the result is 'severity_upgrade' (D3: new message, not edit).
    """
    cache = DedupCache()
    cache.classify(fingerprint="fp-u", severity="warning", event={"msg": "1"}, now=0.0)
    result = cache.classify(
        fingerprint="fp-u",
        severity="error",
        event={"msg": "2"},
        now=50.0,
    )
    assert result == "severity_upgrade"
    assert cache._entries["fp-u"].severity == "error"


def test_severity_downgrade_counter_edit() -> None:
    """
    Given a hot entry with severity='error',
    When a new event arrives with severity='warning' (lower rank),
    Then the result is 'counter_edit' — no severity downgrade triggers a new alert (D3).
    """
    cache = DedupCache()
    cache.classify(fingerprint="fp-d", severity="error", event={"msg": "1"}, now=0.0)
    result = cache.classify(
        fingerprint="fp-d",
        severity="warning",
        event={"msg": "2"},
        now=50.0,
    )
    assert result == "counter_edit"
    # Severity is NOT downgraded
    assert cache._entries["fp-d"].severity == "error"


# ---------------------------------------------------------------------------
# D7 — lifecycle bypass
# ---------------------------------------------------------------------------


def test_lifecycle_bypasses_dedup() -> None:
    """
    Given a DedupCache,
    When classify() is called with fingerprint=None (lifecycle event),
    Then the result is 'lifecycle_bypass' and no entry is stored (D7).
    """
    cache = DedupCache()
    result = cache.classify(
        fingerprint=None,
        severity=None,
        event={"kind": "lifecycle", "msg": "started"},
        now=0.0,
    )
    assert result == "lifecycle_bypass"
    assert len(cache._entries) == 0


# ---------------------------------------------------------------------------
# D5 — byte cap + LRU eviction
# ---------------------------------------------------------------------------


def test_byte_cap_10mb_evicts_lru() -> None:
    """
    Given a DedupCache filled beyond DEDUP_CACHE_MAX_BYTES,
    When evict_if_over_cap() is called,
    Then LRU entries are removed until total_bytes <= 90% of cap (D5).
    """
    cache = DedupCache(max_bytes=1000, max_entries=10_000)

    # Insert entries with known sizes; each ~200 bytes (mocked via byte_size)
    t = 0.0
    for i in range(7):
        fp = f"fp-{i}"
        cache.classify(fingerprint=fp, severity="warning", event={"x": i}, now=t)
        # Override byte_size so we control total_bytes precisely
        cache._entries[fp].byte_size = 200
        t += 1.0

    # Manually sync total_bytes to match overridden sizes
    cache._total_bytes = 7 * 200  # 1400 bytes -> over the 1000 cap

    evicted = cache.evict_if_over_cap()
    assert evicted > 0
    # After eviction: total_bytes <= 900 (90% of 1000)
    assert cache._total_bytes <= 900


def test_entry_cap_10000_evicts() -> None:
    """
    Given a DedupCache with max_entries=5,
    When 6 distinct fingerprints are inserted and evict_if_over_cap() called,
    Then the oldest (LRU) entry is evicted (D5).
    """
    cache = DedupCache(max_bytes=10_485_760, max_entries=5)
    for i in range(6):
        cache.classify(fingerprint=f"fp-{i}", severity="warning", event={}, now=float(i))

    # 6 entries exist now; trigger eviction
    evicted = cache.evict_if_over_cap()
    assert evicted >= 1
    assert len(cache._entries) <= 5


# ---------------------------------------------------------------------------
# D6 — background GC
# ---------------------------------------------------------------------------


def test_gc_removes_entries_past_2x_window() -> None:
    """
    Given entries with last_seen older than 2 * DEDUP_WINDOW_SEC,
    When gc(now) is called,
    Then those stale entries are removed (D6).
    """
    cache = DedupCache()
    # Insert at t=0 -> stale after 600 s
    cache.classify(fingerprint="stale-fp", severity="warning", event={}, now=0.0)
    # Insert at t=500 -> NOT stale at t=601 (only 101 s old)
    cache.classify(fingerprint="fresh-fp", severity="warning", event={}, now=500.0)

    removed = cache.gc(now=601.0)
    assert removed == 1
    assert "stale-fp" not in cache._entries
    assert "fresh-fp" in cache._entries


# ---------------------------------------------------------------------------
# Entry field completeness
# ---------------------------------------------------------------------------


def test_entry_stores_all_fields() -> None:
    """
    Given a classified event,
    When the resulting DedupEntry is inspected,
    Then all required fields are present with correct values.
    """
    cache = DedupCache()
    event = {"kind": "error", "msg": "test"}
    cache.classify(fingerprint="fp-full", severity="error", event=event, now=42.0)

    entry = cache._entries["fp-full"]
    assert isinstance(entry, DedupEntry)
    assert entry.fingerprint == "fp-full"
    assert entry.first_seen == pytest.approx(42.0)
    assert entry.last_seen == pytest.approx(42.0)
    assert entry.count == 1
    assert entry.severity == "error"
    assert entry.latest_event == event
    assert entry.message_id is None  # not set by classify
    assert entry.last_edit_at == 0.0
    assert entry.pending_edit is False
    assert entry.byte_size > 0


# ---------------------------------------------------------------------------
# pending_edit flag on counter bump
# ---------------------------------------------------------------------------


def test_pending_edit_set_on_counter_bump() -> None:
    """
    Given a hot entry with pending_edit=False,
    When a counter_edit classify() occurs,
    Then entry.pending_edit is True.
    """
    cache = DedupCache()
    cache.classify(fingerprint="fp-pe", severity="warning", event={"x": 1}, now=0.0)
    # Ensure pending_edit starts False after first event
    assert cache._entries["fp-pe"].pending_edit is False

    cache.classify(fingerprint="fp-pe", severity="warning", event={"x": 2}, now=10.0)
    assert cache._entries["fp-pe"].pending_edit is True


# ---------------------------------------------------------------------------
# LRU ordering — oldest last_seen evicted first
# ---------------------------------------------------------------------------


def test_eviction_targets_lru_first() -> None:
    """
    Given entries with different last_seen timestamps,
    When evict_if_over_cap() is triggered,
    Then the entry with the smallest last_seen is evicted first.
    """
    cache = DedupCache(max_bytes=100, max_entries=10_000)

    for i, t in enumerate([10.0, 50.0, 90.0]):
        fp = f"fp-{i}"
        cache.classify(fingerprint=fp, severity="warning", event={}, now=t)
        cache._entries[fp].byte_size = 50  # each entry is 50 bytes

    cache._total_bytes = 3 * 50  # 150 bytes, over the 100-byte cap

    cache.evict_if_over_cap()

    # fp-0 (last_seen=10.0) should be evicted first
    assert "fp-0" not in cache._entries
    # At least one of the newer entries should survive
    assert "fp-2" in cache._entries
