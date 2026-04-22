"""Render dispatch — converts event + dedup_entry into HTML text.

Binds service name, handles lifecycle vs alert routing, DedupEntry
object-to-dict conversion.
"""
import time

from snitchbot.shared.domain.services import scrub_event
from snitchbot.sidecar.pipeline.domain.services.alert_render_service import render_alert
from snitchbot.sidecar.pipeline.domain.services.lifecycle_render_service import render_lifecycle
from snitchbot.sidecar.pipeline.domain.services.scrub_render_service import scrub_and_render

__all__ = ["render_dispatch"]


def render_dispatch(*, event: dict, dedup_entry: object = None, service: str) -> str:
    """Render an event to HTML. Routes lifecycle vs alert."""
    if event.get("kind") == "lifecycle":
        return render_lifecycle(event=event, service=service)

    # Convert DedupEntry to dict for render_alert
    if dedup_entry is not None and hasattr(dedup_entry, "count"):
        entry_dict = {
            "count": dedup_entry.count,
            "first_seen": dedup_entry.first_seen,
            "last_seen": dedup_entry.last_seen,
            "severity": dedup_entry.severity,
            "message_id": dedup_entry.message_id,
        }
    elif isinstance(dedup_entry, dict) and "count" in dedup_entry:
        entry_dict = dedup_entry
    else:
        ts = event.get("ts", time.time())
        entry_dict = {
            "count": 1,
            "first_seen": ts,
            "last_seen": ts,
            "severity": event.get("severity", "warning"),
            "message_id": None,
        }

    return scrub_and_render(
        event=event,
        render_fn=lambda *, event: render_alert(
            event=event,
            dedup_entry=entry_dict,
            service=service,
        ),
        scrub_fn=scrub_event,
    )
