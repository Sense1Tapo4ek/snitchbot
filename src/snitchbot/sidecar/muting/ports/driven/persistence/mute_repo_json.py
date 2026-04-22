"""JSON file persistence for mute state (domain-first).

Atomic rename (POSIX-safe): write to .tmp, then rename to final path.
Implements IMuteRepo from muting/app/interfaces/i_mute_repo.py.

The ``async def save`` signature is for interface parity with IMuteRepo —
there is no real async I/O; it delegates to the sync ``_save_sync`` helper.

Layer rules: pathlib + json (stdlib only).
"""
import json
import logging
import time
from pathlib import Path

from snitchbot.sidecar.muting.domain.mute_state_agg import MuteEntry, MuteState

logger = logging.getLogger("snitchbot.sidecar.mute_repo")

__all__ = ["MuteRepoJson"]


class MuteRepoJson:
    """Atomic JSON persistence for mute state (T5).

    Implements the IMuteRepo Protocol directly with a domain-first API:
    - ``save(state)``        accepts a MuteState, serialises active entries.
    - ``load_entries()``     returns list[MuteEntry] (non-expired, or []).

    # Format: flat list of entry dicts (see spec §11.2):
    # [{"fingerprint": str|null, "muted_at": float, "duration_sec": float,
    #   "source_message_id": int|null, "exception_type": str|null}, ...]
    # null fingerprint encodes a global mute.
    # suppressed_count is NOT persisted (§11.4) — resets to 0 on restart.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # IMuteRepo interface
    # ------------------------------------------------------------------

    async def save(self, state: MuteState) -> None:
        """Persist the active (non-expired) entries from *state* (T5).

        ``async`` for interface parity with IMuteRepo — no actual async I/O.
        """
        now = time.time()
        self._save_sync(state, now)

    def load_entries(self) -> list[MuteEntry]:
        """Load previously persisted active (non-expired) entries.

        Returns an empty list if storage is absent or corrupted (§11.2).
        """
        if not self._path.exists():
            return []

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            now = time.time()
            entries = []
            for e in data:
                if not _is_expired_dict(e, now):
                    entries.append(MuteEntry(
                        fingerprint=e["fingerprint"],
                        muted_at=e["muted_at"],
                        duration_sec=e["duration_sec"],
                        source_message_id=e.get("source_message_id"),
                        exception_type=e.get("exception_type"),
                        suppressed_count=0,  # §11.4: suppressed_count not persisted
                        service=e.get("service"),  # F7: forum-mode scoping
                    ))
            return entries
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("corrupted mute state file %r, removing.", self._path)
            self._path.unlink(missing_ok=True)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_sync(self, state: MuteState, now: float) -> None:
        """Sync save: serialise active entries and atomically rename (T5)."""
        entries = [
            {
                "fingerprint": e.fingerprint,
                "muted_at": e.muted_at,
                "duration_sec": e.duration_sec,
                "source_message_id": e.source_message_id,
                "exception_type": e.exception_type,
                "suppressed_count": 0,  # §11.4: not persisted
                "service": e.service,  # F7: forum-mode scoping
            }
            for e in state.get_active_mutes(now)
        ]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        tmp.rename(self._path)


def _is_expired_dict(entry: dict, now: float) -> bool:
    """Return True if the serialised entry's mute has expired."""
    return now >= entry["muted_at"] + entry["duration_sec"]
