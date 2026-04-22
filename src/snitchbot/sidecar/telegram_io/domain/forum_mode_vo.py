"""Forum-mode value object — captures detected chat capabilities at startup.

Layer: domain (stdlib only). Immutable.
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ForumModeVO:
    """Snapshot of forum-related chat capabilities (Invariant F1).

    Attributes:
        is_forum: True iff the configured chat is a forum supergroup.
        can_manage_topics: bot's admin right; None when is_forum=False.
    """

    is_forum: bool
    can_manage_topics: bool | None

    @property
    def fully_capable(self) -> bool:
        """True iff we can create/edit topics in this chat."""
        return self.is_forum and bool(self.can_manage_topics)
