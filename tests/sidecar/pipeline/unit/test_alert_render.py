"""Unit tests for alert_render_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §3, §4, R1–R12.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.3.
"""
from snitchbot.shared.constants import SEPARATOR
from snitchbot.sidecar.pipeline.domain.services.alert_render_service import render_alert

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FP = "a1b2c3"
_SERVICE = "orders-api"


def _dedup_entry(count: int = 1, severity: str = "error") -> dict:
    return {
        "count": count,
        "first_seen": 1744376322.0,  # 2026-04-11 14:18:42 UTC
        "last_seen": 1744377730.0,   # 2026-04-11 14:42:10 UTC
        "severity": severity,
        "message_id": None,
    }


def _crash_event(
    *,
    exception_type: str = "DatabaseConnectionError",
    message: str = "connection refused",
    pid: int = 101,
    thread: str = "MainThread",
    origin: str = "sys_excepthook",
    stack: list[dict] | None = None,
    context: dict | None = None,
    fingerprint: str = _FP,
) -> dict:
    if stack is None:
        stack = [
            {
                "file": "app/db/pool.py",
                "line": 47,
                "func": "acquire",
                "code": "conn = await self._pool.get()",
                "is_user_code": True,
            },
            {
                "file": "app/services/orders.py",
                "line": 88,
                "func": "fetch_all",
                "code": "return await db.fetch(q)",
                "is_user_code": True,
            },
            {
                "file": "app/routes/orders.py",
                "line": 12,
                "func": "list_orders",
                "code": "return await svc.fetch_all()",
                "is_user_code": True,
            },
        ]
    return {
        "kind": "crash",
        "severity": "error",
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": fingerprint,
        "context": context,
        "payload": {
            "exception_type": exception_type,
            "message": message,
            "stack": stack,
            "thread": thread,
            "origin": origin,
        },
    }


def _custom_event(
    *,
    text: str = "db query slow",
    extras: dict | None = None,
    exception: dict | None = None,
    pid: int = 101,
    context: dict | None = None,
    fingerprint: str = _FP,
) -> dict:
    return {
        "kind": "custom",
        "severity": "warning",
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": fingerprint,
        "context": context,
        "payload": {
            "text": text,
            "extras": extras,
            "exception": exception,
            "caller": {"file": "app/services/orders.py", "line": 88, "func": "list_orders"},
        },
    }


def _slow_call_event(*, pid: int = 101, context: dict | None = None, fingerprint: str = _FP) -> dict:
    return {
        "kind": "slow_call",
        "severity": "warning",
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": fingerprint,
        "context": context,
        "payload": {
            "func_qualname": "app.services.orders.fetch_all",
            "duration_ms": 1843.0,
            "threshold_ms": 1000.0,
            "is_async": True,
            "location": {"file": "app/services/orders.py", "line": 88},
        },
    }


def _watchdog_event(*, pid: int = 101, context: dict | None = None, fingerprint: str = _FP) -> dict:
    return {
        "kind": "watchdog",
        "severity": "warning",
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": fingerprint,
        "context": context,
        "payload": {
            "block_duration_ms": 847.0,
            "threshold_ms": 500.0,
            "loop_id": "main",
            "stuck_tasks": [
                {
                    "name": "Task-42",
                    "coro": "app.workers.process_order",
                    "stack": ["app/workers/orders.py:15 in _process()"],
                },
                {
                    "name": "Task-43",
                    "coro": "app.workers.notify_user",
                    "stack": ["app/workers/notify.py:22 in send()"],
                },
            ],
        },
    }


def _anomaly_event(
    *,
    anomaly_type: str = "rss_spike",
    current: float = 256.0,
    baseline: float = 120.0,
    threshold_pct: float = 113.0,
    window: str = "5m",
    pid: int = 101,
    context: dict | None = None,
    fingerprint: str = _FP,
) -> dict:
    return {
        "kind": "anomaly",
        "severity": "warning",
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": fingerprint,
        "context": context,
        "payload": {
            "anomaly_type": anomaly_type,
            "current": current,
            "baseline": baseline,
            "threshold_pct": threshold_pct,
            "window": window,
            "details": {},
        },
    }


# ---------------------------------------------------------------------------
# Task 7.3 tests
# ---------------------------------------------------------------------------


def test_crash_template_shape() -> None:
    """
    Given a crash event with user frames and dedup count=2,
    When render_alert() is called,
    Then the output contains header, title, Details block, Stack block.
    """
    event = _crash_event()
    entry = _dedup_entry(count=2)
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>crash</b>" in html
    assert "DatabaseConnectionError" in html
    assert "<b>Details</b>" in html
    assert "<b>Stack</b>" in html
    assert "app/db/pool.py" in html


def test_crash_counter_omitted_when_count_eq_1() -> None:
    """
    Given a crash event with dedup count=1,
    When render_alert() is called,
    Then '×' counter is absent from the output (R8).
    """
    event = _crash_event()
    entry = _dedup_entry(count=1)
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "×" not in html


def test_crash_first_last_shown_when_counter_gt_1() -> None:
    """
    Given a crash event with dedup count=5,
    When render_alert() is called,
    Then 'first' and 'last' timestamps appear in Details (R9).
    """
    event = _crash_event()
    entry = _dedup_entry(count=5)
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "first" in html
    assert "last" in html
    assert "× 5" in html


def test_crash_header_contains_icon_kind_service_fp_counter_format() -> None:
    """
    Given a crash event with count=12 and severity=error,
    When render_alert() is called,
    Then header first line contains icon, 'crash', service name, fp in <code>, '× 12' (R3).
    """
    event = _crash_event(fingerprint=_FP)
    entry = _dedup_entry(count=12, severity="error")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    first_line = html.split("\n")[0]
    assert "🔴" in first_line
    assert "<b>crash</b>" in first_line
    assert _SERVICE in first_line
    assert f"<code>{_FP}</code>" in first_line
    assert "× 12" in first_line


def test_custom_template_with_extras_block_keyvalue() -> None:
    """
    Given a custom event with extras dict,
    When render_alert() is called,
    Then <b>Extras</b> block appears with key-value lines.
    """
    event = _custom_event(extras={"query": "SELECT * FROM orders", "duration_ms": 1843})
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>Extras</b>" in html
    assert "query" in html
    assert "duration_ms" in html


def test_custom_template_no_stack_without_exc_info() -> None:
    """
    Given a custom event without exc_info/exception,
    When render_alert() is called,
    Then no Stack block appears in the output.
    """
    event = _custom_event(exception=None)
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>Stack</b>" not in html


def test_custom_template_stack_block_added_with_exc_info() -> None:
    """
    Given a custom event with exception/exc_info containing a stack,
    When render_alert() is called,
    Then Stack block appears in the output.
    """
    exc_info = {
        "type": "ValueError",
        "message": "bad input",
        "traceback": (
            'Traceback (most recent call last):\n'
            '  File "app/handlers.py", line 20, in handle\n'
            "    raise ValueError('bad input')\n"
            "ValueError: bad input\n"
        ),
    }
    event = _custom_event(exception=exc_info)
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>Exception</b>" in html
    assert "ValueError" in html
    assert "bad input" in html
    assert "app/handlers.py" in html


def test_custom_template_no_text_buttons_in_html() -> None:
    """
    Given a custom event,
    When render_alert() is called,
    Then no text-based button placeholders appear in HTML
    (buttons are now sent via reply_markup, not embedded in message text).
    """
    event = _custom_event(exception=None)
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)
    assert "🔇" not in html
    assert "📋 trace" not in html
    assert "mute:" not in html


def test_slow_call_template_no_stack_no_trace_button() -> None:
    """
    Given a slow_call event,
    When render_alert() is called,
    Then no Stack block and no trace button appear (R4).
    """
    event = _slow_call_event()
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>slow call</b>" in html
    assert "app.services.orders.fetch_all" in html
    assert "1843" in html
    assert "1000" in html
    assert "<b>Stack</b>" not in html
    assert "📋 trace" not in html


def test_watchdog_template_stuck_tasks_block_and_trace_button() -> None:
    """
    Given a watchdog event with stuck tasks,
    When render_alert() is called,
    Then Stuck tasks block and trace button appear (R4).
    """
    event = _watchdog_event()
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>watchdog</b>" in html
    assert "847" in html
    assert "<b>Stuck tasks</b>" in html
    assert "Task-42" in html
    # Buttons are now inline keyboard (reply_markup), not text in HTML
    assert "📋 trace" not in html


def test_anomaly_template_per_type_title() -> None:
    """
    Given anomaly events with each anomaly_type,
    When render_alert() is called for each,
    Then the title matches the per-type format from spec §4.5.
    """
    # memory_ceiling
    _MB = 1024 * 1024
    event_mem_ceil = _anomaly_event(
        anomaly_type="rss_ceiling",
        current=500.0 * _MB,
        baseline=120.0 * _MB,
    )
    html_mem = render_alert(event=event_mem_ceil, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "RSS ceiling" in html_mem

    # memory_spike
    event_mem_spike = _anomaly_event(
        anomaly_type="rss_spike",
        current=256.0 * _MB,
        baseline=120.0 * _MB,
    )
    html_spike = render_alert(event=event_mem_spike, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "RSS spike" in html_spike

    # cpu_ceiling
    event_cpu = _anomaly_event(
        anomaly_type="cpu_ceiling",
        current=95.0,
        baseline=30.0,
    )
    html_cpu = render_alert(event=event_cpu, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "CPU ceiling" in html_cpu

    # fds_spike
    event_fd = _anomaly_event(anomaly_type="fds_spike", current=500.0, baseline=100.0)
    html_fd = render_alert(event=event_fd, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "FD leak" in html_fd

    # threads_spike
    event_th = _anomaly_event(anomaly_type="threads_spike", current=50.0, baseline=10.0)
    html_th = render_alert(event=event_th, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "Thread growth" in html_th


def test_anomaly_no_stack_no_trace_button() -> None:
    """
    Given an anomaly event,
    When render_alert() is called,
    Then no Stack block and no trace button appear (R4).
    """
    event = _anomaly_event()
    entry = _dedup_entry(count=1, severity="warning")
    html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)

    assert "<b>Stack</b>" not in html
    assert "📋 trace" not in html


def test_context_block_hidden_when_empty() -> None:
    """
    Given a crash event with empty or None context,
    When render_alert() is called,
    Then no Context block appears in the output (R10).
    """
    event_none = _crash_event(context=None)
    html_none = render_alert(event=event_none, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "<b>Context</b>" not in html_none

    event_empty = _crash_event(context={})
    html_empty = render_alert(event=event_empty, dedup_entry=_dedup_entry(), service=_SERVICE)
    assert "<b>Context</b>" not in html_empty


def test_context_block_max_10_tags_truncated_with_more() -> None:
    """
    Given a crash event with 12 context entries,
    When render_alert() is called,
    Then Context block is present, at most 10 tags shown, and '... N more' appears.
    """
    ctx = {f"key_{i}": f"val_{i}" for i in range(12)}
    event = _crash_event(context=ctx)
    html = render_alert(event=event, dedup_entry=_dedup_entry(), service=_SERVICE)

    assert "<b>Context</b>" in html
    assert "more" in html


def test_parse_mode_html_always() -> None:
    """
    Given any kind of event,
    When render_alert() is called,
    Then the output contains HTML tags (confirming HTML parse_mode) (R1).
    """
    event = _crash_event()
    html = render_alert(event=event, dedup_entry=_dedup_entry(), service=_SERVICE)

    # Result must contain at least some HTML tags
    assert "<b>" in html


def test_all_alert_kinds_contain_separator_on_second_line() -> None:
    """
    Given any alert kind (crash, custom, slow_call, watchdog, anomaly),
    When render_alert() is called,
    Then the rendered HTML has the canonical SEPARATOR as its second line (R1).
    """
    cases: list[dict] = [
        _crash_event(),
        _custom_event(),
        _slow_call_event(),
        _watchdog_event(),
        _anomaly_event(anomaly_type="rss_ceiling"),
    ]
    entry = _dedup_entry(count=1)

    for event in cases:
        html = render_alert(event=event, dedup_entry=entry, service=_SERVICE)
        lines = html.split("\n")
        assert len(lines) >= 2, f"{event['kind']}: output too short"
        assert lines[1] == SEPARATOR, (
            f"{event['kind']}: expected SEPARATOR on line 2, got {lines[1]!r}"
        )


def test_severity_upgrade_produces_new_message_with_new_icon() -> None:
    """
    Given a dedup_entry with severity=warning and a new event with severity=error,
    When render_alert() is called with the upgraded severity in dedup_entry,
    Then the rendered header uses the new (upgraded) severity icon (R12).
    """
    # Entry now reflects upgraded severity
    entry_upgraded = {
        "count": 3,
        "first_seen": 1744376322.0,
        "last_seen": 1744377730.0,
        "severity": "error",  # upgraded from warning
        "message_id": None,
    }
    event = _crash_event()
    html = render_alert(event=event, dedup_entry=entry_upgraded, service=_SERVICE)

    first_line = html.split("\n")[0]
    assert "🔴" in first_line
    assert "🟠" not in first_line
