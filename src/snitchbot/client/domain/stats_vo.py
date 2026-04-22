"""Client-side stats counter aggregate.

NOT frozen: this is a counter-style aggregator updated in place by the
client. Public API returns copies via ``snapshot()``. This is an explicit
exception to the frozen-dataclass rule, justified by the counter pattern.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class ClientStats:
    events_sent: int = 0
    dropped_buffer_full: int = 0
    sidecar_unavailable: int = 0
    sidecar_dead: int = 0
    config_rejected: int = 0
    invalid_events: int = 0
    oversized: int = 0
    internal_errors: int = 0
    init_conflict: int = 0
    called_before_init: int = 0
    notify_exc_info_no_exception: int = 0

    def snapshot(self) -> dict:
        """Return a plain dict snapshot for diagnostics / status command."""
        from dataclasses import asdict
        return asdict(self)
