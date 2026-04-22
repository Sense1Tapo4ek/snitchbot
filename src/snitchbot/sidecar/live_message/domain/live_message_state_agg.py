"""Sidecar domain: live message persistent state.

Pure Python stdlib - no frameworks, no I/O.

Invariants:
    LM1: one dashboard per (chat_id, thread_id) pair - one per topic in
         forum mode, one per chat in simple mode.
    LM7: no persistence across sidecar restarts.
    F8 : forum-mode failures (pinning) never propagate - enforced in the
         workflow layer, not here.
"""
from dataclasses import dataclass, field

__all__ = ["LiveMessageState", "DashboardEntry"]

@dataclass(slots=True)
class DashboardEntry:
    """One pinned dashboard in one chat/topic (LM1).

    Fields:
        message_id        : Telegram message_id once sent; None before first send (LM5).
        last_content_hash : md5/sha hash of the last rendered HTML (LM3).
        created_at        : wall-clock time when the message was first created.
    """

    message_id: int | None = field(default=None)
    last_content_hash: str = field(default="")
    created_at: float = field(default=0.0)

@dataclass(slots=True)
class LiveMessageState:
    """In-memory map of pinned dashboards, keyed by (chat_id, thread_id).

    Simple mode: all callers pass thread_id=None, producing one entry
    at key ``(chat_id, None)`` - same behaviour as the pre-forum-mode
    single-message design.

    Forum mode: one entry per topic, keyed by ``(chat_id, thread_id)``.

    Legacy `service` field is preserved for backwards-compatible
    construction in the composition root; it is no longer used for
    lookups and defaults to "" so callers that do not care may omit it.
    """

    service: str = field(default="")
    _entries: dict[tuple[str, int | None], DashboardEntry] = field(
        default_factory=dict,
        repr=False,
    )

    # ------------------------------------------------------------------
    # message_id accessors
    # ------------------------------------------------------------------

    def get_message_id(self, chat_id: str, thread_id: int | None) -> int | None:
        """Return the pinned-dashboard message_id for this (chat, topic), or None."""
        entry = self._entries.get((chat_id, thread_id))
        return entry.message_id if entry is not None else None

    def set_message_id(
        self,
        chat_id: str,
        thread_id: int | None,
        message_id: int,
    ) -> None:
        """Record the Telegram message_id for this (chat, topic)."""
        entry = self._entries.get((chat_id, thread_id))
        if entry is None:
            entry = DashboardEntry()
            self._entries[(chat_id, thread_id)] = entry
        entry.message_id = message_id

    # ------------------------------------------------------------------
    # content hash accessors
    # ------------------------------------------------------------------

    def get_content_hash(self, chat_id: str, thread_id: int | None) -> str:
        """Return the last-rendered content hash, or "" if none yet."""
        entry = self._entries.get((chat_id, thread_id))
        return entry.last_content_hash if entry is not None else ""

    def set_content_hash(
        self,
        chat_id: str,
        thread_id: int | None,
        content_hash: str,
    ) -> None:
        """Record the last-rendered content hash for this (chat, topic)."""
        entry = self._entries.get((chat_id, thread_id))
        if entry is None:
            entry = DashboardEntry()
            self._entries[(chat_id, thread_id)] = entry
        entry.last_content_hash = content_hash

    # ------------------------------------------------------------------
    # created_at accessors
    # ------------------------------------------------------------------

    def get_created_at(self, chat_id: str, thread_id: int | None) -> float:
        entry = self._entries.get((chat_id, thread_id))
        return entry.created_at if entry is not None else 0.0

    def set_created_at(
        self,
        chat_id: str,
        thread_id: int | None,
        created_at: float,
    ) -> None:
        entry = self._entries.get((chat_id, thread_id))
        if entry is None:
            entry = DashboardEntry()
            self._entries[(chat_id, thread_id)] = entry
        entry.created_at = created_at

    # ------------------------------------------------------------------
    # Introspection helpers (used by shutdown edits and tests)
    # ------------------------------------------------------------------

    def all_entries(self) -> list[tuple[str, int | None, DashboardEntry]]:
        """Return a snapshot list of (chat_id, thread_id, entry) triples."""
        return [(chat, th, e) for (chat, th), e in self._entries.items()]
