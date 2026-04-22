"""Integration tests for MuteRepoJson — real filesystem, tmp dirs.

Invariants: T5 (atomic rename), T11 (source_message_id persisted),
§11.4 (suppressed_count not persisted).

New domain-first API:
  - save(state: MuteState) -> None  (async)
  - load_entries() -> list[MuteEntry]
"""
import asyncio
import json
import time
from pathlib import Path

import pytest

from snitchbot.sidecar.muting.domain.mute_state_agg import MuteEntry, MuteState
from snitchbot.sidecar.muting.ports.driven.persistence.mute_repo_json import MuteRepoJson

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_with_fp(
    fp: str = "abc123",
    duration: float = 3600.0,
    source_message_id: int | None = None,
) -> MuteState:
    """Return a MuteState with one per-fp mute applied."""
    state = MuteState()
    state.mute(
        fingerprint=fp,
        duration_sec=duration,
        source_message_id=source_message_id,
        now=time.time(),
    )
    return state


def _state_with_global(duration: float = 3600.0) -> MuteState:
    """Return a MuteState with a global mute applied."""
    state = MuteState()
    state.mute(
        fingerprint=None,
        duration_sec=duration,
        source_message_id=None,
        now=time.time(),
    )
    return state


def _save_sync(repo: MuteRepoJson, state: MuteState) -> None:
    """Drive the async save method synchronously in tests."""
    asyncio.run(repo.save(state))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> MuteRepoJson:
    return MuteRepoJson(path=tmp_path / "mutes.json")


# ---------------------------------------------------------------------------
# T5: atomic rename
# ---------------------------------------------------------------------------


class TestAtomicRename:
    def test_atomic_rename_tmp_file(self, tmp_path: Path):
        """
        Given a MuteRepoJson backed by a path,
        When save() is called,
        Then the .tmp file is created and then renamed to the final path (T5).
        Verified by confirming the .tmp file does NOT exist after save.
        """
        path = tmp_path / "mutes.json"
        repo = MuteRepoJson(path=path)
        _save_sync(repo, _state_with_fp())

        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_save_creates_valid_json(self, repo: MuteRepoJson, tmp_path: Path):
        """
        Given a MuteState with one active entry,
        When save() is called,
        Then the resulting file contains valid JSON with one entry.
        """
        _save_sync(repo, _state_with_fp())
        path = tmp_path / "mutes.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_save_empty_state(self, repo: MuteRepoJson, tmp_path: Path):
        """
        Given an empty MuteState (no active mutes),
        When save() is called,
        Then the file contains an empty JSON array.
        """
        _save_sync(repo, MuteState())
        path = tmp_path / "mutes.json"
        data = json.loads(path.read_text())
        assert data == []


# ---------------------------------------------------------------------------
# load_entries: returns MuteEntry instances
# ---------------------------------------------------------------------------


class TestLoadEntries:
    def test_round_trip_returns_mute_entry(self, repo: MuteRepoJson):
        """
        Given a MuteState with one active per-fp mute,
        When save() then load_entries() is called,
        Then a list containing one MuteEntry is returned.
        """
        state = _state_with_fp(fp="abc123")
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert len(entries) == 1
        assert isinstance(entries[0], MuteEntry)
        assert entries[0].fingerprint == "abc123"

    def test_load_entries_returns_empty_when_file_absent(self, repo: MuteRepoJson):
        """
        Given the mutes file does not exist,
        When load_entries() is called,
        Then an empty list is returned (no error).
        """
        assert repo.load_entries() == []

    def test_load_entries_filters_expired(self, tmp_path: Path):
        """
        Given a JSON file with one active and one already-expired entry,
        When load_entries() is called,
        Then only the active entry is returned.
        """
        path = tmp_path / "mutes.json"
        now = time.time()
        path.write_text(json.dumps([
            # active entry
            {"fingerprint": "abc123", "muted_at": now, "duration_sec": 3600.0,
             "source_message_id": None, "suppressed_count": 0},
            # expired entry (muted 2h ago, 1h duration)
            {"fingerprint": "exp456", "muted_at": now - 7200.0, "duration_sec": 3600.0,
             "source_message_id": None, "suppressed_count": 0},
        ]))
        repo = MuteRepoJson(path=path)
        entries = repo.load_entries()
        assert len(entries) == 1
        assert entries[0].fingerprint == "abc123"

    def test_load_entries_returns_empty_when_all_expired(self, tmp_path: Path):
        """
        Given a JSON file where all entries are expired,
        When load_entries() is called,
        Then an empty list is returned.
        """
        path = tmp_path / "mutes.json"
        now = time.time()
        path.write_text(json.dumps([
            {"fingerprint": "fp1", "muted_at": now - 7200.0, "duration_sec": 3600.0,
             "source_message_id": None, "suppressed_count": 0},
        ]))
        repo = MuteRepoJson(path=path)
        assert repo.load_entries() == []

    def test_load_entries_global_mute(self, repo: MuteRepoJson):
        """
        Given a global mute in state,
        When saved and reloaded,
        Then returned entry has fingerprint=None.
        """
        state = _state_with_global()
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert len(entries) == 1
        assert entries[0].fingerprint is None

    def test_suppressed_count_reset_to_zero_on_load(self, repo: MuteRepoJson):
        """
        §11.4: suppressed_count is NOT persisted.
        Given a state where an entry had suppressed_count > 0,
        When saved and reloaded,
        Then the loaded entry has suppressed_count == 0.
        """
        state = _state_with_fp(fp="abc123")
        # Simulate some suppressions before save
        entry = state.get_entry("abc123")
        assert entry is not None
        entry.suppressed_count = 7
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert entries[0].suppressed_count == 0


# ---------------------------------------------------------------------------
# load_entries: corrupted JSON
# ---------------------------------------------------------------------------


class TestCorruptedJson:
    def test_corrupted_json_returns_empty_and_deletes_file(self, tmp_path: Path):
        """
        Given a JSON file with corrupted content,
        When load_entries() is called,
        Then the file is deleted and an empty list is returned (§11.2).
        """
        path = tmp_path / "mutes.json"
        path.write_text("this is not json {{{{")
        repo = MuteRepoJson(path=path)
        result = repo.load_entries()
        assert result == []
        assert not path.exists()

    def test_corrupted_json_partial_returns_empty(self, tmp_path: Path):
        """
        Given a JSON file that is cut short (partial),
        When load_entries() is called,
        Then the file is deleted and an empty list is returned.
        """
        path = tmp_path / "mutes.json"
        path.write_text('{"fingerprint": "abc"')
        repo = MuteRepoJson(path=path)
        result = repo.load_entries()
        assert result == []
        assert not path.exists()

    def test_missing_required_field_returns_empty(self, tmp_path: Path):
        """
        Given a JSON file where an entry is missing 'duration_sec',
        When load_entries() is called,
        Then the file is deleted and an empty list is returned.
        """
        path = tmp_path / "mutes.json"
        path.write_text(json.dumps([{"fingerprint": "abc123", "muted_at": time.time()}]))
        repo = MuteRepoJson(path=path)
        result = repo.load_entries()
        assert result == []
        assert not path.exists()


# ---------------------------------------------------------------------------
# T11: source_message_id persisted
# ---------------------------------------------------------------------------


class TestSourceMessageIdPersisted:
    def test_persists_source_message_id(self, repo: MuteRepoJson):
        """
        Given a mute with source_message_id=42,
        When save() then load_entries() is called,
        Then source_message_id is preserved (T11).
        """
        state = _state_with_fp(fp="abc123", source_message_id=42)
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert len(entries) == 1
        assert entries[0].source_message_id == 42

    def test_persists_none_source_message_id(self, repo: MuteRepoJson):
        """
        Given a mute with source_message_id=None,
        When save() then load_entries() is called,
        Then source_message_id is None in the loaded entry.
        """
        state = _state_with_fp(fp="abc123", source_message_id=None)
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert entries[0].source_message_id is None


# ---------------------------------------------------------------------------
# §7.3: exception_type persisted
# ---------------------------------------------------------------------------


class TestExceptionTypePersisted:
    def test_persists_exception_type(self, repo: MuteRepoJson):
        """
        Given a mute applied with exception_type='ValueError',
        When save() then load_entries() is called,
        Then exception_type is preserved (§7.3).
        """
        state = MuteState()
        state.mute(
            fingerprint="abc123",
            duration_sec=3600.0,
            source_message_id=None,
            now=time.time(),
            exception_type="ValueError",
        )
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert len(entries) == 1
        assert entries[0].exception_type == "ValueError"

    def test_persists_none_exception_type(self, repo: MuteRepoJson):
        """
        Given a mute applied without exception_type,
        When save() then load_entries() is called,
        Then exception_type is None in the loaded entry.
        """
        state = _state_with_fp(fp="abc123")
        _save_sync(repo, state)
        entries = repo.load_entries()
        assert entries[0].exception_type is None
