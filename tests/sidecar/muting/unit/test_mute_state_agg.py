"""Unit tests for MuteState domain aggregate.

No mocks — pure domain, stdlib only.

Invariants covered: T6, T7, T9, E8, E9, D7.
"""
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteEntry, MuteState

NOW = 1_000_000.0  # fixed epoch for determinism


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state() -> MuteState:
    return MuteState()


def _global_muted(state: MuteState, duration: float = 3600.0) -> MuteState:
    """Apply a global mute and return the state."""
    state.mute(fingerprint=None, duration_sec=duration, source_message_id=None, now=NOW)
    return state


def _fp_muted(state: MuteState, fp: str = "abc123", duration: float = 3600.0) -> MuteState:
    """Apply a per-fingerprint mute and return the state."""
    state.mute(fingerprint=fp, duration_sec=duration, source_message_id=None, now=NOW)
    return state


# ---------------------------------------------------------------------------
# T6, E8: critical events are NEVER suppressed
# ---------------------------------------------------------------------------


class TestCriticalBypass:
    def test_is_muted_returns_false_for_critical_with_global_mute(self):
        """
        Given a global mute is active,
        When checking a critical event,
        Then is_muted returns False (T6, E8).
        """
        state = _global_muted(_make_state())
        result = state.is_muted(fingerprint="abc123", severity="critical", now=NOW)
        assert result is False

    def test_is_muted_returns_false_for_critical_with_per_fp_mute(self):
        """
        Given a per-fingerprint mute is active,
        When checking a critical event with that fingerprint,
        Then is_muted returns False (T6, E8).
        """
        state = _fp_muted(_make_state(), fp="abc123")
        result = state.is_muted(fingerprint="abc123", severity="critical", now=NOW)
        assert result is False

    def test_is_muted_returns_false_for_critical_no_mutes(self):
        """
        Given no active mutes,
        When checking a critical event,
        Then is_muted returns False.
        """
        state = _make_state()
        result = state.is_muted(fingerprint="abc123", severity="critical", now=NOW)
        assert result is False


# ---------------------------------------------------------------------------
# T7, E9, D7: lifecycle events (fingerprint=None) are NEVER suppressed
# ---------------------------------------------------------------------------


class TestLifecycleBypass:
    def test_is_muted_returns_false_for_lifecycle_no_mutes(self):
        """
        Given no mutes,
        When fingerprint is None (lifecycle event),
        Then is_muted returns False (T7, E9, D7).
        """
        state = _make_state()
        result = state.is_muted(fingerprint=None, severity="info", now=NOW)
        assert result is False

    def test_is_muted_returns_false_for_lifecycle_with_global_mute(self):
        """
        Given a global mute is active,
        When fingerprint is None (lifecycle event),
        Then is_muted returns False (T7, E9, D7).
        """
        state = _global_muted(_make_state())
        result = state.is_muted(fingerprint=None, severity="info", now=NOW)
        assert result is False

    def test_is_muted_returns_false_for_lifecycle_severity_none(self):
        """
        Given no mutes,
        When fingerprint is None and severity is None,
        Then is_muted returns False.
        """
        state = _make_state()
        result = state.is_muted(fingerprint=None, severity=None, now=NOW)
        assert result is False


# ---------------------------------------------------------------------------
# Global mute suppression
# ---------------------------------------------------------------------------


class TestGlobalMute:
    def test_is_muted_true_when_global_active(self):
        """
        Given a global mute is active,
        When checking a non-critical event with a fingerprint,
        Then is_muted returns True.
        """
        state = _global_muted(_make_state())
        result = state.is_muted(fingerprint="abc123", severity="error", now=NOW)
        assert result is True

    def test_is_muted_false_when_global_expired(self):
        """
        Given a global mute that has expired,
        When checking an event after expiry,
        Then is_muted returns False (lazy eviction).
        """
        state = _make_state()
        state.mute(fingerprint=None, duration_sec=10.0, source_message_id=None, now=NOW)
        # Check at NOW + 11 (past expiry)
        result = state.is_muted(fingerprint="abc123", severity="error", now=NOW + 11.0)
        assert result is False


# ---------------------------------------------------------------------------
# Per-fingerprint mute suppression
# ---------------------------------------------------------------------------


class TestPerFingerprintMute:
    def test_is_muted_true_when_per_fp_active(self):
        """
        Given a per-fingerprint mute is active,
        When checking an event with matching fingerprint,
        Then is_muted returns True.
        """
        state = _fp_muted(_make_state(), fp="abc123")
        result = state.is_muted(fingerprint="abc123", severity="error", now=NOW)
        assert result is True

    def test_is_muted_false_for_different_fingerprint(self):
        """
        Given a mute on fp 'abc123',
        When checking fp 'xyz789',
        Then is_muted returns False.
        """
        state = _fp_muted(_make_state(), fp="abc123")
        result = state.is_muted(fingerprint="xyz789", severity="error", now=NOW)
        assert result is False

    def test_is_muted_lazy_eviction_on_expiration(self):
        """
        Given a per-fp mute with 10s duration,
        When checking at NOW + 11,
        Then is_muted returns False (lazy eviction on check).
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=10.0, source_message_id=None, now=NOW)
        result = state.is_muted(fingerprint="abc123", severity="error", now=NOW + 11.0)
        assert result is False


# ---------------------------------------------------------------------------
# suppressed_count tracking
# ---------------------------------------------------------------------------


class TestSuppressedCount:
    def test_suppressed_count_incremented_on_global_mute(self):
        """
        Given a global mute is active,
        When is_muted is called twice for a non-critical event,
        Then global mute suppressed_count == 2.
        """
        state = _global_muted(_make_state())
        state.is_muted(fingerprint="abc123", severity="error", now=NOW)
        state.is_muted(fingerprint="abc123", severity="warning", now=NOW)
        active = state.get_active_mutes(NOW)
        global_entry = next(e for e in active if e.fingerprint is None)
        assert global_entry.suppressed_count == 2

    def test_suppressed_count_incremented_on_per_fp_mute(self):
        """
        Given a per-fp mute is active,
        When is_muted is called three times with that fingerprint,
        Then that entry's suppressed_count == 3.
        """
        state = _fp_muted(_make_state(), fp="abc123")
        for _ in range(3):
            state.is_muted(fingerprint="abc123", severity="error", now=NOW)
        active = state.get_active_mutes(NOW)
        fp_entry = next(e for e in active if e.fingerprint == "abc123")
        assert fp_entry.suppressed_count == 3

    def test_suppressed_count_not_incremented_for_critical(self):
        """
        Given a global mute,
        When a critical event bypasses,
        Then suppressed_count remains 0.
        """
        state = _global_muted(_make_state())
        state.is_muted(fingerprint="abc123", severity="critical", now=NOW)
        active = state.get_active_mutes(NOW)
        global_entry = next(e for e in active if e.fingerprint is None)
        assert global_entry.suppressed_count == 0

    def test_suppressed_count_not_incremented_for_lifecycle(self):
        """
        Given a global mute,
        When a lifecycle event (fingerprint=None) bypasses,
        Then suppressed_count remains 0.
        """
        state = _global_muted(_make_state())
        state.is_muted(fingerprint=None, severity="info", now=NOW)
        active = state.get_active_mutes(NOW)
        global_entry = next(e for e in active if e.fingerprint is None)
        assert global_entry.suppressed_count == 0


# ---------------------------------------------------------------------------
# T9: repeat mute on already-muted is rejected
# ---------------------------------------------------------------------------


class TestRepeatMuteRejected:
    def test_repeat_mute_on_already_muted_fingerprint_rejected(self):
        """
        Given a per-fp mute is active,
        When attempting to mute the same fingerprint again,
        Then mute() returns False (T9).
        """
        state = _fp_muted(_make_state(), fp="abc123")
        result = state.mute(
            fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW
        )
        assert result is False

    def test_repeat_global_mute_rejected(self):
        """
        Given a global mute is active,
        When attempting to mute globally again,
        Then mute() returns False (T9).
        """
        state = _global_muted(_make_state())
        result = state.mute(
            fingerprint=None, duration_sec=3600.0, source_message_id=None, now=NOW
        )
        assert result is False

    def test_mute_succeeds_first_time(self):
        """
        Given no active mute for fingerprint,
        When muting,
        Then mute() returns True.
        """
        state = _make_state()
        result = state.mute(
            fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW
        )
        assert result is True

    def test_mute_on_expired_entry_succeeds(self):
        """
        Given a mute that has expired,
        When muting again with the same fingerprint,
        Then mute() returns True (expired is not considered 'already muted').
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=5.0, source_message_id=None, now=NOW)
        result = state.mute(
            fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW + 10.0
        )
        assert result is True


# ---------------------------------------------------------------------------
# unmute
# ---------------------------------------------------------------------------


class TestUnmute:
    def test_unmute_removes_per_fp_entry(self):
        """
        Given a per-fp mute is active,
        When unmuting,
        Then unmute() returns True and entry is removed.
        """
        state = _fp_muted(_make_state(), fp="abc123")
        result = state.unmute(fingerprint="abc123")
        assert result is True
        assert state.is_muted(fingerprint="abc123", severity="error", now=NOW) is False

    def test_unmute_removes_global_entry(self):
        """
        Given a global mute is active,
        When calling unmute(fingerprint=None),
        Then unmute() returns True and global mute is removed.
        """
        state = _global_muted(_make_state())
        result = state.unmute(fingerprint=None)
        assert result is True
        assert state.is_muted(fingerprint="abc123", severity="error", now=NOW) is False

    def test_unmute_returns_false_if_not_muted(self):
        """
        Given no active mute,
        When calling unmute,
        Then unmute() returns False.
        """
        state = _make_state()
        result = state.unmute(fingerprint="abc123")
        assert result is False

    def test_unmute_global_returns_false_if_not_muted(self):
        """
        Given no global mute,
        When calling unmute(fingerprint=None),
        Then unmute() returns False.
        """
        state = _make_state()
        result = state.unmute(fingerprint=None)
        assert result is False


# ---------------------------------------------------------------------------
# get_active_mutes
# ---------------------------------------------------------------------------


class TestGetActiveMutes:
    def test_get_active_mutes_empty_on_fresh_state(self):
        """
        Given fresh MuteState,
        When calling get_active_mutes,
        Then returns empty list.
        """
        state = _make_state()
        assert state.get_active_mutes(NOW) == []

    def test_get_active_mutes_excludes_expired(self):
        """
        Given a mute that expired,
        When calling get_active_mutes after expiry,
        Then the expired entry is not included.
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=5.0, source_message_id=None, now=NOW)
        result = state.get_active_mutes(NOW + 10.0)
        assert result == []

    def test_get_active_mutes_includes_active(self):
        """
        Given one global and one per-fp mute,
        When calling get_active_mutes,
        Then both entries are returned.
        """
        state = _make_state()
        state.mute(fingerprint=None, duration_sec=3600.0, source_message_id=None, now=NOW)
        state.mute(fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW)
        result = state.get_active_mutes(NOW)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# source_message_id stored
# ---------------------------------------------------------------------------


class TestSourceMessageId:
    def test_source_message_id_stored_in_entry(self):
        """
        Given a mute with source_message_id,
        When checking get_active_mutes,
        Then entry has correct source_message_id (T11).
        """
        state = _make_state()
        state.mute(
            fingerprint="abc123", duration_sec=3600.0, source_message_id=42, now=NOW
        )
        active = state.get_active_mutes(NOW)
        assert len(active) == 1
        assert active[0].source_message_id == 42

    def test_source_message_id_none_allowed(self):
        """
        Given a command-initiated mute (no source_message_id),
        When checking get_active_mutes,
        Then entry has source_message_id == None.
        """
        state = _make_state()
        state.mute(
            fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW
        )
        active = state.get_active_mutes(NOW)
        assert active[0].source_message_id is None


# ---------------------------------------------------------------------------
# MuteEntry: expired notification even when suppressed_count == 0
# ---------------------------------------------------------------------------


class TestMuteExpiredWithZeroSuppressed:
    def test_mute_expired_notification_even_when_suppressed_zero(self):
        """
        Given a mute with suppressed_count == 0 (nothing was suppressed),
        When the mute expires,
        Then get_active_mutes does not include it (it's still valid to notify even at 0).
        The mute entry is accessible before expiry regardless of suppressed_count.
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=10.0, source_message_id=None, now=NOW)
        # Before expiry: entry accessible
        active_before = state.get_active_mutes(NOW + 5.0)
        assert len(active_before) == 1
        assert active_before[0].suppressed_count == 0
        # After expiry: entry gone
        active_after = state.get_active_mutes(NOW + 11.0)
        assert active_after == []


# ---------------------------------------------------------------------------
# MuteEntry fields
# ---------------------------------------------------------------------------


class TestMuteEntryFields:
    def test_mute_entry_has_required_fields(self):
        """
        Given a MuteEntry,
        When inspecting it,
        Then all required fields exist with correct defaults.
        """
        entry = MuteEntry(
            fingerprint="abc123",
            muted_at=NOW,
            duration_sec=3600.0,
            source_message_id=None,
        )
        assert entry.fingerprint == "abc123"
        assert entry.muted_at == NOW
        assert entry.duration_sec == 3600.0
        assert entry.source_message_id is None
        assert entry.exception_type is None
        assert entry.suppressed_count == 0

    def test_mute_entry_suppressed_count_mutable(self):
        """
        Given a MuteEntry,
        When incrementing suppressed_count,
        Then it can be mutated (it's not frozen).
        """
        entry = MuteEntry(
            fingerprint="abc123",
            muted_at=NOW,
            duration_sec=3600.0,
            source_message_id=None,
        )
        entry.suppressed_count += 1
        assert entry.suppressed_count == 1


# ---------------------------------------------------------------------------
# get_entry
# ---------------------------------------------------------------------------


class TestGetEntry:
    def test_get_entry_returns_per_fp_hit(self):
        """
        Given a per-fp mute on 'abc123',
        When get_entry('abc123') is called,
        Then the MuteEntry is returned.
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW)
        entry = state.get_entry("abc123")
        assert entry is not None
        assert entry.fingerprint == "abc123"

    def test_get_entry_returns_none_on_per_fp_miss(self):
        """
        Given a per-fp mute on 'abc123',
        When get_entry('xyz789') is called,
        Then None is returned.
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW)
        assert state.get_entry("xyz789") is None

    def test_get_entry_returns_global_when_fingerprint_none(self):
        """
        Given a global mute is active,
        When get_entry(None) is called,
        Then the global MuteEntry is returned.
        """
        state = _global_muted(_make_state())
        entry = state.get_entry(None)
        assert entry is not None
        assert entry.fingerprint is None

    def test_get_entry_returns_none_for_global_when_no_global_mute(self):
        """
        Given no global mute,
        When get_entry(None) is called,
        Then None is returned.
        """
        state = _make_state()
        assert state.get_entry(None) is None


# ---------------------------------------------------------------------------
# active_count
# ---------------------------------------------------------------------------


class TestActiveCount:
    def test_active_count_zero_on_fresh_state(self):
        """
        Given fresh MuteState,
        When active_count(now) is called,
        Then 0 is returned.
        """
        state = _make_state()
        assert state.active_count(NOW) == 0

    def test_active_count_one_after_global_mute(self):
        """
        Given one global mute applied,
        When active_count(now) is called,
        Then 1 is returned.
        """
        state = _global_muted(_make_state())
        assert state.active_count(NOW) == 1

    def test_active_count_two_with_global_and_per_fp(self):
        """
        Given one global mute and one per-fp mute,
        When active_count(now) is called,
        Then 2 is returned.
        """
        state = _global_muted(_make_state())
        state.mute(fingerprint="abc123", duration_sec=3600.0, source_message_id=None, now=NOW)
        assert state.active_count(NOW) == 2

    def test_active_count_excludes_expired(self):
        """
        Given a mute that expired before now,
        When active_count(now) is called,
        Then 0 is returned.
        """
        state = _make_state()
        state.mute(fingerprint="abc123", duration_sec=60.0, source_message_id=None, now=NOW)
        assert state.active_count(NOW + 120.0) == 0

    def test_active_count_does_not_mutate(self):
        """
        Given active mutes,
        When active_count(now) is called multiple times,
        Then the count is stable (method is non-mutating).
        """
        state = _fp_muted(_make_state(), fp="abc123")
        assert state.active_count(NOW) == 1
        assert state.active_count(NOW) == 1
