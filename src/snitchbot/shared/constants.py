"""Shared internal constants for the snitchbot telemetry library.

Single source of truth for timing, size, and capacity limits used across the
client, sidecar, and shared kernel. Values are taken from the Phase 1 Shared
Kernel description (see docs/superpowers/plans/2026-04-11-implementation-plan.md §134).

All constants MUST be immutable scalars (int, float, or str). No lists, no
dicts, no mutable containers — importers rely on referential stability.
"""

from typing import Final

# --- Bot message layout -------------------------------------------------------

SEPARATOR: Final[str] = "━" * 18
"""Horizontal divider between header and body in every structured bot message.

Width is fixed at 18 U+2501 characters. This is the single source of truth —
every renderer, query, facade that emits structured Telegram text MUST import
this constant rather than hard-coding the string. Invariant R1.
"""

# --- Dedup & rate-limit -------------------------------------------------------

DEDUP_WINDOW_SEC: int = 300
"""Dedup window duration in seconds (5 minutes)."""

DEDUP_CACHE_MAX_BYTES: int = 10_485_760
"""Dedup cache byte cap (10 MiB)."""

DEDUP_CACHE_MAX_ENTRIES: int = 10_000
"""Dedup cache entry cap."""

# --- Vitals & live message ----------------------------------------------------

VITALS_SAMPLE_SEC: int = 5
"""Interval between vitals samples."""

FDS_SAMPLE_INTERVAL_SEC: int = 15
"""Interval between file-descriptor count samples."""

LIVE_MESSAGE_TICK_SEC: int = 10
"""Interval between live-message refresh ticks."""

# --- Watchdog -----------------------------------------------------------------

WATCHDOG_THRESHOLD_MS: int = 500
"""Loop-lag threshold that triggers a watchdog event (milliseconds)."""

WATCHDOG_COOLDOWN_SEC: int = 10
"""Cooldown between consecutive watchdog emissions."""

WATCHDOG_CHECK_INTERVAL_SEC: float = 0.2
"""Interval at which the watchdog samples event-loop lag."""

WATCHDOG_ESCALATION_WINDOW_SEC: int = 60
"""Window during which repeated watchdog hits escalate severity."""

# --- Event / transport limits -------------------------------------------------

MAX_EVENT_SIZE: int = 8192
"""Hard cap on an encoded event's size in bytes (post-truncation)."""

TG_MESSAGE_LIMIT: int = 4096
"""Telegram message body character limit."""

QUEUE_MAX: int = 256
"""Max pending events in the client -> sidecar queue."""

# --- IPC / handshake ----------------------------------------------------------

HANDSHAKE_RESPONSE_TIMEOUT_MS: int = 500
"""Deadline for the sidecar hello response (milliseconds)."""

SOCKET_POLL_TIMEOUT_SEC: float = 2.0
"""Poll timeout on the sidecar AF_UNIX socket."""

PINGER_INTERVAL_SEC: float = 0.1
"""Interval of the client-side liveness pinger."""
