"""Watchdog severity escalation policy — pure domain service.

CI14: first hit in window -> base severity; repeated hit within escalation window -> escalate.

Multi-threshold severity (v2):
- block_ms >= threshold_ms -> 'warning'
- block_ms >= error_threshold_ms -> 'error'
- block_ms >= critical_threshold_ms -> 'critical'

Escalation window: within the window, repeated hits escalate one level above
the threshold-based severity (capped at 'critical').

No frameworks, no I/O, stdlib only.
"""
from snitchbot.shared.constants import WATCHDOG_ESCALATION_WINDOW_SEC

_SEVERITY_ORDER = ("warning", "error", "critical")


class WatchdogPolicyService:
    """Stateful severity escalation tracker with multi-threshold support.

    Args:
        escalation_window_sec: Duration of the escalation window in seconds.
        error_threshold_ms: Block duration for severity 'error'. None = disabled.
        critical_threshold_ms: Block duration for severity 'critical'. None = disabled.
    """

    def __init__(
        self,
        escalation_window_sec: float = WATCHDOG_ESCALATION_WINDOW_SEC,
        error_threshold_ms: int | None = None,
        critical_threshold_ms: int | None = None,
    ) -> None:
        self._escalation_window_sec = escalation_window_sec
        self._error_threshold_ms = error_threshold_ms
        self._critical_threshold_ms = critical_threshold_ms
        self._first_hit_in_window_at: float = 0.0

    def compute_severity(self, now: float, block_ms: float = 0.0) -> str:
        """Return severity based on block duration and escalation window.

        1. Determine base severity from block_ms thresholds.
        2. If within escalation window, escalate one level.
        3. Cap at 'critical'.

        Args:
            now: Current monotonic timestamp.
            block_ms: How long the event loop was blocked (milliseconds).

        Returns:
            'warning', 'error', or 'critical'.
        """
        # 1. Base severity from thresholds
        base = "warning"
        if self._error_threshold_ms is not None and block_ms >= self._error_threshold_ms:
            base = "error"
        if self._critical_threshold_ms is not None and block_ms >= self._critical_threshold_ms:
            base = "critical"

        # 2. Escalation window
        if (
            self._first_hit_in_window_at == 0.0
            or now - self._first_hit_in_window_at > self._escalation_window_sec
        ):
            # Start a new escalation window
            self._first_hit_in_window_at = now
            return base

        # Within window — escalate one level above base
        idx = _SEVERITY_ORDER.index(base)
        escalated_idx = min(idx + 1, len(_SEVERITY_ORDER) - 1)
        return _SEVERITY_ORDER[escalated_idx]
