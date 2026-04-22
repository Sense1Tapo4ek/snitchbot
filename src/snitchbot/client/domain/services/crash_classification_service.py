"""Crash classification service — Task 4.1.

Pure domain function (stdlib only). Classifies exception type -> severity.

      docs/superpowers/specs/2026-04-11-event-model-design.md §5
Invariants:
- CI7: KeyboardInterrupt is 'error', not 'critical' (handled by SIGINT path)
"""

def classify_crash_severity(exc_type: type[BaseException]) -> str:
    """Return 'critical' or 'error' based on exception type.

    Critical: MemoryError, SystemExit (and subclasses).
    Error: everything else, including KeyboardInterrupt (CI7 — SIGINT path
    handles it to avoid double-alerting crash + lifecycle).
    """
    if issubclass(exc_type, MemoryError):
        return "critical"
    if issubclass(exc_type, SystemExit):
        return "critical"
    return "error"
