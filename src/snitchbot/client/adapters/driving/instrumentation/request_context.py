"""request_context — driving adapter for request-scoped context propagation.

Uses contextvars.ContextVar so context propagates through asyncio.create_task
automatically (native Python behaviour) but NOT through threading.Thread
(documented non-goal, CI32).

Spec:
    docs/superpowers/specs/2026-04-11-client-internals-design.md §7
    docs/superpowers/specs/2026-04-11-public-api-design.md §6

Invariants:
    CI27: sets contextvar on enter, restores on exit
    CI28: trace_id=None remains None — no synthetic ID generated
    CI29: nested contexts merge extras, inner overrides outer
    CI30: parent trace_id inherited if child doesn't specify
    CI31: propagates through asyncio.create_task (native Python)
    CI32: does NOT propagate through threading.Thread (documented)
    E10:  empty context (no trace_id, no extras) becomes None via
          get_current_context()
"""
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# Single module-level ContextVar.  Default is None (no active context).
_current_context: ContextVar[dict | None] = ContextVar(
    "snitchbot_context", default=None
)


@contextmanager
def request_context(
    *,
    trace_id: str | None = None,
    **extras: Any,
) -> Generator[dict, None, None]:
    """Set request-scoped context for snitchbot events.

    Context is inherited from any enclosing request_context (nesting).
    trace_id is inherited from parent if not specified (CI30).
    extras are merged: parent values are base, inner values override (CI29).

    Yields the context dict for introspection (mostly useful in tests).

    After the block exits — even on exception — the previous context is
    restored (CI27).
    """
    parent = _current_context.get()

    # CI30: inherit trace_id from parent if not explicitly given.
    effective_trace_id: str | None
    if trace_id is not None:
        effective_trace_id = trace_id
    elif parent is not None:
        effective_trace_id = parent.get("trace_id")  # may itself be None
    else:
        effective_trace_id = None  # CI28: never synthesize

    # CI29: merge extras — parent as base, child overrides.
    merged_extras: dict[str, Any] = {}
    if parent is not None:
        merged_extras.update(parent.get("extras", {}))
    merged_extras.update(extras)

    ctx: dict = {
        "trace_id": effective_trace_id,
        "extras": merged_extras,
    }

    token = _current_context.set(ctx)
    try:
        yield ctx
    finally:
        _current_context.reset(token)  # CI27: always restore


def get_current_context() -> dict | None:
    """Return the active context dict, or None if there is none.

    Per E10: an empty context (no trace_id, no extras) is considered a no-op
    and returns None rather than an empty-looking dict.  This prevents
    attaching meaningless ``{"trace_id": null, "context": {}}`` noise to
    every event.
    """
    ctx = _current_context.get()
    if ctx is None:
        return None

    # E10: context that carries no information -> treat as absent.
    if ctx.get("trace_id") is None and not ctx.get("extras"):
        return None

    return ctx
