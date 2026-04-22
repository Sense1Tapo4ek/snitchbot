"""Flow tests for EditFlusherWorkflow — periodic edit dispatcher (D4).

Spec: docs/superpowers/specs/2026-04-11-dedup-rate-limit-design.md §3.5, D4.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 6.3.

Uses real DedupCache (no mocks) — this is a flow test between two domain-adjacent
objects in the same bounded context. DedupCache is injected, not mocked, because
EditFlusherWorkflow is pure computation that depends on DedupCache state.
"""
from snitchbot.sidecar.pipeline.app.workflows.edit_flusher_workflow import EditFlusherWorkflow
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(msg: str = "boom") -> dict:
    return {"kind": "error", "msg": msg}


def _seed_entry(
    cache: DedupCache,
    fp: str,
    now: float,
    *,
    message_id: int = 42,
    pending_edit: bool = True,
    last_edit_at: float = 0.0,
) -> None:
    """Seed a DedupCache entry with controlled state."""
    cache.classify(fingerprint=fp, severity="error", event=_make_event(), now=now)
    entry = dict(cache.entries())[fp]
    entry.message_id = message_id
    entry.pending_edit = pending_edit
    entry.last_edit_at = last_edit_at


# ---------------------------------------------------------------------------
# test_edit_flusher_returns_pending_edits
# ---------------------------------------------------------------------------


class TestEditFlusherReturnsPendingEdits:
    def test_returns_one_edit_for_pending_entry(self) -> None:
        """
        Given a DedupCache with one entry that has pending_edit=True and last_edit_at=0,
        When tick() is called at now=10.0 (>= 5s threshold),
        Then exactly one edit dict is returned with the correct fingerprint.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-001", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        assert len(edits) == 1
        assert edits[0].payload["fingerprint"] == "fp-001"

    def test_edit_dict_contains_required_keys(self) -> None:
        """
        Given a pending entry with message_id=99,
        When tick() dispatches it,
        Then the returned dict has all required keys.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-keys", now=0.0, message_id=99, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        assert len(edits) == 1
        edit = edits[0]
        assert "fingerprint" in edit.payload
        assert "event" in edit.payload
        assert "count" in edit.payload
        assert "severity" in edit.payload
        assert "message_id" in edit.payload
        assert edit.payload["message_id"] == 99

    def test_no_edits_when_nothing_pending(self) -> None:
        """
        Given a DedupCache with entries where pending_edit=False,
        When tick() is called,
        Then an empty list is returned.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-nop", now=0.0, pending_edit=False, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        assert edits == []


# ---------------------------------------------------------------------------
# test_edit_throttled_1_per_5s — D4
# ---------------------------------------------------------------------------


class TestEditThrottled1Per5s:
    def test_edit_dispatched_when_interval_elapsed(self) -> None:
        """
        Given a pending entry with last_edit_at=0,
        When tick() is called at now=5.0 (exactly at threshold),
        Then edit is dispatched (now - last_edit_at == 5.0 >= 5.0).
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-thresh", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=5.0)

        # Assert
        assert len(edits) == 1

    def test_edit_suppressed_when_interval_not_elapsed(self) -> None:
        """
        Given a pending entry with last_edit_at=0,
        When tick() is called at now=4.9 (< 5s threshold),
        Then no edit is dispatched (throttled).
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-throttle", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=4.9)

        # Assert
        assert edits == []

    def test_second_tick_suppressed_within_5s(self) -> None:
        """
        Given a pending entry dispatched at t=10,
        When another pending_edit arrives and tick() is called at t=12 (2s later),
        Then the second tick is suppressed (only 2s elapsed since last_edit_at=10).
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-seq", now=0.0, pending_edit=True, last_edit_at=0.0)

        # First tick — dispatches
        edits1 = flusher.tick(now=10.0)
        assert len(edits1) == 1

        # Re-mark pending (simulate new event arriving)
        entry = dict(cache.entries())["fp-seq"]
        entry.pending_edit = True

        # Act — second tick too soon
        edits2 = flusher.tick(now=12.0)

        # Assert
        assert edits2 == []

    def test_second_tick_allowed_after_5s(self) -> None:
        """
        Given a pending entry dispatched at t=10,
        When tick() is called at t=15 (5s later) and pending_edit is True again,
        Then the edit is dispatched.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-seq2", now=0.0, pending_edit=True, last_edit_at=0.0)

        # First tick
        flusher.tick(now=10.0)

        # Re-mark pending
        entry = dict(cache.entries())["fp-seq2"]
        entry.pending_edit = True

        # Act — second tick after 5s
        edits = flusher.tick(now=15.0)

        # Assert
        assert len(edits) == 1


# ---------------------------------------------------------------------------
# test_burst_events_produce_limited_edits — D4
# ---------------------------------------------------------------------------


class TestBurstEventsProduceLimitedEdits:
    def test_50_events_10s_max_2_edits(self) -> None:
        """
        Given 50 events for the same fingerprint arriving over 10s,
        When tick() is called every 2s (at t=0,2,4,6,8,10),
        Then at most 2 edits are dispatched for that fingerprint (D4: 1 edit per 5s).

        t=0:  classify x50, first is new_alert, rest are counter_edit -> pending_edit=True
        tick(0):  0 - 0 = 0 < 5 -> suppressed (last_edit_at=0 set by classify no-op,
                  actually last_edit_at starts at 0.0 from _create_or_reset)
        tick(2):  2 - 0 = 2 < 5 -> suppressed
        tick(4):  4 - 0 = 4 < 5 -> suppressed
        tick(6):  6 - 0 = 6 >= 5 -> dispatched, last_edit_at=6
        tick(8):  8 - 6 = 2 < 5 -> suppressed
        tick(10): 10 - 6 = 4 < 5 -> suppressed
        Total dispatched: 1 (not 2 as upper bound; the spec says MAX 2, and 1 <= 2)
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        # Burst: 50 classify calls at t=0
        now_classify = 0.0
        for i in range(50):
            cache.classify(
                fingerprint="fp-burst",
                severity="error",
                event=_make_event(f"event-{i}"),
                now=now_classify,
            )

        # Set message_id so it behaves like a posted alert
        entry = dict(cache.entries())["fp-burst"]
        entry.message_id = 1

        total_edits = 0
        for t in [0, 2, 4, 6, 8, 10]:
            edits = flusher.tick(now=float(t))
            total_edits += len(edits)

        # Assert: D4 guarantees max 1 edit per 5s -> over 10s max 2 edits
        assert total_edits <= 2

    def test_burst_with_enough_time_produces_edits(self) -> None:
        """
        Given 50 events for same fp, ticking every 6s (past the 5s threshold),
        When ticked 3 times (at t=6, 12, 18),
        Then up to 3 edits can be dispatched (one per tick if pending).
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        cache.classify(
            fingerprint="fp-burst2",
            severity="error",
            event=_make_event(),
            now=0.0,
        )
        entry = dict(cache.entries())["fp-burst2"]
        entry.message_id = 2
        entry.pending_edit = True

        total_edits = 0
        for t in [6, 12, 18]:
            edits = flusher.tick(now=float(t))
            total_edits += len(edits)
            # Re-mark pending for next tick
            if dict(cache.entries()).get("fp-burst2"):
                dict(cache.entries())["fp-burst2"].pending_edit = True

        assert total_edits == 3


# ---------------------------------------------------------------------------
# test_only_single_processing_path — D4
# ---------------------------------------------------------------------------


class TestOnlySingleProcessingPath:
    def test_classify_does_not_immediately_produce_edit_payload(self) -> None:
        """
        Given an event classified as counter_edit,
        When classify() returns,
        Then no edit payload is produced — the entry only has pending_edit=True.

        This confirms the single processing path: edits only come from tick().
        """
        # Arrange
        cache = DedupCache()

        # First event: new_alert
        cache.classify(fingerprint="fp-path", severity="error", event=_make_event(), now=0.0)

        # Second event: counter_edit
        result = cache.classify(fingerprint="fp-path", severity="error", event=_make_event("2nd"), now=1.0)

        # Assert: classify returns a string classification, not a payload
        assert isinstance(result, str)
        assert result == "counter_edit"

        # The entry has pending_edit=True but no edit has been dispatched
        entry = dict(cache.entries())["fp-path"]
        assert entry.pending_edit is True

    def test_edit_payload_only_produced_by_tick(self) -> None:
        """
        Given multiple counter_edit events,
        When edits are needed,
        Then they come exclusively from EditFlusherWorkflow.tick(), not from classify().
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        cache.classify(fingerprint="fp-only", severity="error", event=_make_event(), now=0.0)
        cache.classify(fingerprint="fp-only", severity="error", event=_make_event("2"), now=1.0)
        cache.classify(fingerprint="fp-only", severity="error", event=_make_event("3"), now=2.0)

        # No edits yet — tick not called
        entry = dict(cache.entries())["fp-only"]
        assert entry.pending_edit is True

        # Now tick — edits come through
        edits = flusher.tick(now=10.0)
        assert len(edits) == 1
        assert edits[0].payload["fingerprint"] == "fp-only"


# ---------------------------------------------------------------------------
# test_pending_edit_flag_cleared_after_dispatch
# ---------------------------------------------------------------------------


class TestPendingEditFlagClearedAfterDispatch:
    def test_flag_cleared_after_dispatch(self) -> None:
        """
        Given a pending entry,
        When tick() dispatches the edit,
        Then entry.pending_edit is False afterward.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-clear", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        assert len(edits) == 1
        entry = dict(cache.entries())["fp-clear"]
        assert entry.pending_edit is False

    def test_last_edit_at_updated_after_dispatch(self) -> None:
        """
        Given a pending entry with last_edit_at=0,
        When tick() dispatches at now=10.0,
        Then entry.last_edit_at == 10.0.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-ts", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        flusher.tick(now=10.0)

        # Assert
        entry = dict(cache.entries())["fp-ts"]
        assert entry.last_edit_at == 10.0

    def test_second_tick_no_duplicate(self) -> None:
        """
        Given a dispatched entry (pending_edit cleared),
        When tick() is called again without new events,
        Then no edit is dispatched.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)
        _seed_entry(cache, "fp-nodup", now=0.0, pending_edit=True, last_edit_at=0.0)

        # First tick
        flusher.tick(now=10.0)

        # Act — second tick (pending_edit is now False)
        edits = flusher.tick(now=20.0)

        # Assert
        assert edits == []


# ---------------------------------------------------------------------------
# test_tick_returns_empty_when_no_pending
# ---------------------------------------------------------------------------


class TestTickReturnsEmptyWhenNoPending:
    def test_empty_cache(self) -> None:
        """
        Given an empty DedupCache,
        When tick() is called,
        Then an empty list is returned.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        # Act
        edits = flusher.tick(now=100.0)

        # Assert
        assert edits == []

    def test_cache_with_only_new_alerts_no_pending(self) -> None:
        """
        Given a cache with entries that were classified as new_alert (pending_edit=False),
        When tick() is called,
        Then empty list returned.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        for i in range(5):
            cache.classify(
                fingerprint=f"fp-new-{i}",
                severity="error",
                event=_make_event(),
                now=float(i),
            )

        # Act
        edits = flusher.tick(now=100.0)

        # Assert — new_alert entries never set pending_edit
        assert edits == []


# ---------------------------------------------------------------------------
# test_multiple_fingerprints_independent
# ---------------------------------------------------------------------------


class TestMultipleFingerprintsIndependent:
    def test_two_fps_each_throttled_independently(self) -> None:
        """
        Given two fingerprints each with pending_edit=True,
        fp-A with last_edit_at=0 (ready),
        fp-B with last_edit_at=8 (not ready at t=10),
        When tick() is called at now=10.0,
        Then fp-A is dispatched but fp-B is throttled.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        _seed_entry(cache, "fp-A", now=0.0, pending_edit=True, last_edit_at=0.0)
        _seed_entry(cache, "fp-B", now=0.0, pending_edit=True, last_edit_at=8.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        dispatched_fps = {e.payload["fingerprint"] for e in edits}
        assert "fp-A" in dispatched_fps
        assert "fp-B" not in dispatched_fps

    def test_three_fps_all_ready(self) -> None:
        """
        Given three fingerprints all with pending_edit=True and last_edit_at=0,
        When tick() is called at now=10.0,
        Then all three are dispatched.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        for fp in ["fp-X", "fp-Y", "fp-Z"]:
            _seed_entry(cache, fp, now=0.0, pending_edit=True, last_edit_at=0.0)

        # Act
        edits = flusher.tick(now=10.0)

        # Assert
        assert len(edits) == 3
        dispatched = {e.payload["fingerprint"] for e in edits}
        assert dispatched == {"fp-X", "fp-Y", "fp-Z"}

    def test_each_fp_tracks_its_own_last_edit_at(self) -> None:
        """
        Given fp-C dispatched at t=6, fp-D dispatched at t=8,
        When tick() is called at t=11,
        Then fp-C (11-6=5 >= 5) is ready but fp-D (11-8=3 < 5) is not.
        """
        # Arrange
        cache = DedupCache()
        flusher = EditFlusherWorkflow(_dedup_cache=cache)

        _seed_entry(cache, "fp-C", now=0.0, pending_edit=True, last_edit_at=0.0)
        _seed_entry(cache, "fp-D", now=0.0, pending_edit=True, last_edit_at=0.0)

        # Tick at t=6: fp-C dispatched
        edits6 = flusher.tick(now=6.0)
        assert len(edits6) == 2  # Both ready at t=6 (6-0=6 >= 5)

        # Re-mark both pending
        entries = dict(cache.entries())
        entries["fp-C"].pending_edit = True
        entries["fp-D"].last_edit_at = 8.0  # Simulate fp-D was last edited at t=8
        entries["fp-D"].pending_edit = True

        # Act: tick at t=11
        edits11 = flusher.tick(now=11.0)

        # Assert: fp-C (11-6=5 >= 5) dispatched, fp-D (11-8=3 < 5) not
        dispatched = {e.payload["fingerprint"] for e in edits11}
        assert "fp-C" in dispatched
        assert "fp-D" not in dispatched
