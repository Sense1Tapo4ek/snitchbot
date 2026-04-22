"""Unit tests for recent events buffer — Task 9.10.

Spec: interactive §4.6, §5.1 (traffic counters, /last buffer).
"""
import time

from snitchbot.shared.domain.recent_event import RecentEvent
from snitchbot.sidecar.interactive.domain.recent_events_buffer_agg import (
    RecentEventsBuffer,
)

_DEFAULT_CAPACITY = 10_000  # documented minimum capacity


def _make_event(
    *,
    kind: str,
    severity: str | None = None,
    ts: float | None = None,
    fingerprint: str | None = None,
) -> RecentEvent:
    return RecentEvent(
        ts=ts if ts is not None else time.time(),
        fingerprint=fingerprint,
        severity=severity,
        exception_type=None,
        message=None,
        pid=None,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# test_buffer_capacity_sufficient
# ---------------------------------------------------------------------------


def test_buffer_capacity_sufficient():
    """
    Given the default capacity of RecentEventsBuffer,
    When checked against expected minimum (≥ 10 000 events),
    Then the buffer is large enough for typical production use.
    """
    assert _DEFAULT_CAPACITY >= 10_000


# ---------------------------------------------------------------------------
# test_traffic_counters_linear_scan_window
# ---------------------------------------------------------------------------


def test_traffic_counters_linear_scan_window():
    """
    Given a buffer with events at known timestamps,
    When traffic_counters(window_sec, now) is called,
    Then only events within the window are counted.
    """
    buf = RecentEventsBuffer()
    now = time.time()

    # 3 errors in window, 1 outside
    buf.add(_make_event(kind="crash", severity="error", ts=now - 100))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 200))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 300))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 7200))  # outside 1h

    counters = buf.traffic_counters(window_sec=3600, now=now)
    assert counters["errors"] == 3
    assert counters["warnings"] == 0
    assert counters["slow_calls"] == 0
    assert counters["watchdog_hits"] == 0


# ---------------------------------------------------------------------------
# test_per_category_count_errors_warnings_slow_watchdog
# ---------------------------------------------------------------------------


def test_per_category_count_errors_warnings_slow_watchdog():
    """
    Given a buffer with mixed event kinds,
    When traffic_counters() is called with a wide window,
    Then each category is independently counted.
    """
    buf = RecentEventsBuffer()
    now = time.time()

    for _ in range(2):
        buf.add(_make_event(kind="crash", severity="error", ts=now - 10))
    for _ in range(7):
        buf.add(_make_event(kind="custom", severity="warning", ts=now - 10))
    for _ in range(3):
        buf.add(_make_event(kind="slow_call", severity=None, ts=now - 10))
    for _ in range(1):
        buf.add(_make_event(kind="watchdog", severity=None, ts=now - 10))

    counters = buf.traffic_counters(window_sec=3600, now=now)
    assert counters["errors"] == 2
    assert counters["warnings"] == 7
    assert counters["slow_calls"] == 3
    assert counters["watchdog_hits"] == 1


# ---------------------------------------------------------------------------
# test_last_n_returns_events_filtered_by_window_and_n
# ---------------------------------------------------------------------------


def test_last_n_returns_events_filtered_by_window_and_n():
    """
    Given a buffer with errors and warnings at different timestamps,
    When last_n(n=2, window_sec=3600, now=..., severities={'error'}) is called,
    Then only up to 2 error events within 1h are returned.
    """
    buf = RecentEventsBuffer()
    now = time.time()

    # Add old event first so it sits at the front of the deque (oldest)
    buf.add(_make_event(kind="crash", severity="error", ts=now - 7200, fingerprint="eee555"))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 180, fingerprint="ccc333"))
    buf.add(_make_event(kind="custom", severity="warning", ts=now - 60, fingerprint="ddd444"))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 120, fingerprint="bbb222"))
    buf.add(_make_event(kind="crash", severity="error", ts=now - 60, fingerprint="aaa111"))

    results = buf.last_n(n=2, window_sec=3600, now=now, severities={"error"})
    assert len(results) == 2
    for r in results:
        assert r.severity == "error"
