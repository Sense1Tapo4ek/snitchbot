"""Scrub-then-render wrapper.

Applies secret scrubbing to a deep copy of the event before passing it to
the render function, so the original event is never mutated.

Invariants:
  S1 — scrubbing is applied before render.
  S2 — the original event dict is not mutated.
  R7 — scrubbing covers all text fields before render.
"""
from collections.abc import Callable

def scrub_and_render(
    *,
    event: dict,
    render_fn: Callable[..., str],
    scrub_fn: Callable[[dict], dict],
) -> str:
    """Scrub event fields then render to HTML.

    Args:
        event:     The original event dict. Never mutated (S2).
        render_fn: Callable that accepts ``event=<dict>`` and returns HTML.
        scrub_fn:  Callable that accepts a dict and returns a deep-copied,
                   scrubbed version (e.g. ``scrub_event`` from shared kernel).

    Returns:
        Rendered HTML string produced from the scrubbed event copy.
    """
    scrubbed = scrub_fn(event)  # deep copy; original is untouched (S2)
    return render_fn(event=scrubbed)

__all__ = ["scrub_and_render"]
