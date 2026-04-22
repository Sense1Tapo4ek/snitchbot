"""Unit tests for ``fingerprint_service.compute_fingerprint``.

Spec: ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §6.
Invariants: E3 (deterministic, computed from payload), D2 (per-kind inputs),
D7 (lifecycle never dedup'd -> ``None``).

Pure domain tests — no mocks. Builds ``Event`` aggregates with payload VOs
and asserts the hex fingerprint has the expected shape and equivalence
relations.
"""
import re

import pytest

from snitchbot import __version__
from snitchbot.shared.domain.event_agg import Event
from snitchbot.shared.domain.event_kind_vo import EventKind
from snitchbot.shared.domain.payloads import (
    AnomalyPayload,
    CrashPayload,
    CustomPayload,
    LifecyclePayload,
    SlowCallPayload,
    WatchdogPayload,
)
from snitchbot.shared.domain.payloads.crash_payload_vo import StackFrame
from snitchbot.shared.domain.payloads.custom_payload_vo import Caller
from snitchbot.shared.domain.payloads.slow_call_payload_vo import Location
from snitchbot.shared.domain.payloads.watchdog_payload_vo import StuckTask
from snitchbot.shared.domain.services import compute_fingerprint
from snitchbot.shared.domain.severity_vo import Severity  # noqa: F401  (type alias used in annotations)

HEX6_RE = re.compile(r"^[0-9a-f]{6}$")


def _frame(
    file: str, line: int, func: str, code: str | None = None, *, is_user_code: bool = True
) -> StackFrame:
    return StackFrame(file=file, line=line, func=func, code=code, is_user_code=is_user_code)


def _event(
    kind: EventKind,
    payload,
    *,
    severity: Severity | None = "error",
    context: dict | None = None,
) -> Event:
    return Event(
        v=__version__,
        ts=1712828400.0,
        kind=kind,
        severity=severity,
        pid=123,
        trace_id=None,
        context=context,
        payload=payload,
    )


def _crash(
    exception_type: str,
    message: str,
    frames: tuple[StackFrame, ...],
) -> CrashPayload:
    return CrashPayload(
        exception_type=exception_type,
        message=message,
        stack=frames,
        thread="MainThread",
        origin="sys_excepthook",
    )


class TestFingerprintCrash:
    def test_fingerprint_crash_uses_exception_type_and_top3_user_frames(self):
        """
        Given two crashes with same exception_type and same top-3 user frames,
        When compute_fingerprint is called,
        Then both yield the same hash; changing the top frame changes it.
        (Invariant D2.)
        """
        frames = (
            _frame("app/a.py", 10, "foo", is_user_code=True),
            _frame("app/b.py", 20, "bar", is_user_code=True),
            _frame("app/c.py", 30, "baz", is_user_code=True),
            _frame("app/d.py", 40, "tail", is_user_code=True),
        )
        e1 = _event(EventKind.CRASH, _crash("OSError", "msg-A", frames))
        e2 = _event(EventKind.CRASH, _crash("OSError", "msg-A", frames))
        assert compute_fingerprint(e1) == compute_fingerprint(e2)

        altered = (
            _frame("app/OTHER.py", 99, "different", is_user_code=True),
            frames[1],
            frames[2],
            frames[3],
        )
        e3 = _event(EventKind.CRASH, _crash("OSError", "msg-A", altered))
        assert compute_fingerprint(e1) != compute_fingerprint(e3)

    def test_fingerprint_crash_ignores_message(self):
        """
        Given two crashes with same type+frames but different messages,
        When fingerprints are computed,
        Then they are equal (message excluded per spec §6).
        """
        frames = (
            _frame("app/a.py", 10, "foo", is_user_code=True),
            _frame("app/b.py", 20, "bar", is_user_code=True),
            _frame("app/c.py", 30, "baz", is_user_code=True),
        )
        e1 = _event(EventKind.CRASH, _crash("ValueError", "id=123", frames))
        e2 = _event(EventKind.CRASH, _crash("ValueError", "id=999", frames))
        assert compute_fingerprint(e1) == compute_fingerprint(e2)

    def test_fingerprint_crash_only_user_code_frames_contribute(self):
        """
        Given a crash stack mixing user-code and non-user-code frames,
        When fingerprints are computed,
        Then only is_user_code=True frames drive the hash.
        Two events with same user frames but different lib frames yield same fingerprint.
        """
        user_frames = (
            _frame("app/a.py", 10, "foo", is_user_code=True),
            _frame("app/b.py", 20, "bar", is_user_code=True),
        )
        lib_frame_v1 = _frame("lib/x.py", 5, "libfn", is_user_code=False)
        lib_frame_v2 = _frame("lib/y.py", 9, "otherfn", is_user_code=False)

        stack_a = (lib_frame_v1,) + user_frames
        stack_b = (lib_frame_v2,) + user_frames

        e1 = _event(EventKind.CRASH, _crash("RuntimeError", "x", stack_a))
        e2 = _event(EventKind.CRASH, _crash("RuntimeError", "x", stack_b))
        assert compute_fingerprint(e1) == compute_fingerprint(e2)

        # Changing a user frame should change the fingerprint.
        different_user = (
            _frame("app/OTHER.py", 77, "different", is_user_code=True),
            user_frames[1],
        )
        e3 = _event(EventKind.CRASH, _crash("RuntimeError", "x", different_user))
        assert compute_fingerprint(e1) != compute_fingerprint(e3)


class TestFingerprintCustom:
    def _custom(self, text: str, caller: Caller | None = None) -> CustomPayload:
        return CustomPayload(
            text=text, extras=None, exception=None, source="notify", caller=caller
        )

    def test_fingerprint_custom_uses_text_and_caller_file_line(self):
        """
        Given two notify calls from different caller sites,
        When fingerprints are computed,
        Then they differ; matching text+file+line yields the same hash.
        """
        caller_a = Caller(file="app/x.py", line=10, func="fn_a")
        caller_b = Caller(file="app/y.py", line=10, func="fn_b")
        caller_c = Caller(file="app/x.py", line=99, func="fn_c")

        payload_a = self._custom("db slow", caller_a)
        payload_a2 = self._custom("db slow", Caller(file="app/x.py", line=10, func="fn_a"))
        payload_b = self._custom("db slow", caller_b)
        payload_c = self._custom("db slow", caller_c)

        e_a = _event(EventKind.CUSTOM, payload_a)
        e_a2 = _event(EventKind.CUSTOM, payload_a2)
        e_b = _event(EventKind.CUSTOM, payload_b)
        e_c = _event(EventKind.CUSTOM, payload_c)

        assert compute_fingerprint(e_a) == compute_fingerprint(e_a2)
        assert compute_fingerprint(e_a) != compute_fingerprint(e_b)
        assert compute_fingerprint(e_a) != compute_fingerprint(e_c)

        e_other_text = _event(
            EventKind.CUSTOM, self._custom("other text", caller_a)
        )
        assert compute_fingerprint(e_a) != compute_fingerprint(e_other_text)

    def test_fingerprint_custom_no_caller_uses_empty_defaults(self):
        """
        Given a custom event with caller=None,
        When fingerprints are computed for two such events with same text,
        Then they match (both fall back to empty file/zero line).
        """
        p1 = self._custom("same text", caller=None)
        p2 = self._custom("same text", caller=None)
        e1 = _event(EventKind.CUSTOM, p1)
        e2 = _event(EventKind.CUSTOM, p2)
        assert compute_fingerprint(e1) == compute_fingerprint(e2)


class TestFingerprintSlowCall:
    def _slow(self, qualname: str, is_async: bool = False) -> SlowCallPayload:
        return SlowCallPayload(
            func_qualname=qualname,
            duration_ms=1200.0,
            threshold_ms=1000.0,
            is_async=is_async,
            location=Location(file="app/mod.py", line=42),
        )

    def test_fingerprint_slow_call_uses_qualname_only(self):
        """
        Given slow_call events for the same func_qualname with different
        duration and threshold,
        When fingerprints are computed,
        Then the hash is identical (only qualname matters, per spec §6).
        """
        p1 = SlowCallPayload(
            func_qualname="app.mod.fetch",
            duration_ms=1200.0,
            threshold_ms=1000.0,
            is_async=True,
            location=Location(file="app/mod.py", line=10),
        )
        p2 = SlowCallPayload(
            func_qualname="app.mod.fetch",
            duration_ms=9999.0,
            threshold_ms=500.0,
            is_async=False,
            location=Location(file="other/mod.py", line=99),
        )
        p3 = SlowCallPayload(
            func_qualname="app.mod.OTHER",
            duration_ms=1200.0,
            threshold_ms=1000.0,
            is_async=True,
            location=Location(file="app/mod.py", line=10),
        )
        e1 = _event(EventKind.SLOW_CALL, p1, severity="warning")
        e2 = _event(EventKind.SLOW_CALL, p2, severity="warning")
        e3 = _event(EventKind.SLOW_CALL, p3, severity="warning")

        assert compute_fingerprint(e1) == compute_fingerprint(e2)
        assert compute_fingerprint(e1) != compute_fingerprint(e3)


class TestFingerprintWatchdog:
    def _wd(self, tasks: tuple[StuckTask, ...]) -> WatchdogPayload:
        return WatchdogPayload(
            block_duration_ms=500.0,
            threshold_ms=200.0,
            loop_id="loop-main",
            stuck_tasks=tasks,
        )

    def test_fingerprint_watchdog_uses_top_stuck_task_coro_or_generic(self):
        """
        Given a watchdog event with empty stuck_tasks,
        Then the fingerprint equals hash of ("watchdog", "generic").
        Given non-empty stuck_tasks,
        Then the top task's coro drives the fingerprint (not the name).
        """
        empty = _event(
            EventKind.WATCHDOG, self._wd(()), severity="warning"
        )
        with_task = _event(
            EventKind.WATCHDOG,
            self._wd((StuckTask(name="Task-42", coro="app.tasks.heavy_job", stack=()),)),
            severity="warning",
        )
        other_coro = _event(
            EventKind.WATCHDOG,
            self._wd((StuckTask(name="Task-42", coro="app.tasks.OTHER", stack=()),)),
            severity="warning",
        )
        same_coro_diff_name = _event(
            EventKind.WATCHDOG,
            self._wd((StuckTask(name="Task-99", coro="app.tasks.heavy_job", stack=()),)),
            severity="warning",
        )

        assert compute_fingerprint(empty) != compute_fingerprint(with_task)
        assert compute_fingerprint(with_task) != compute_fingerprint(other_coro)
        # Same coro but different task name -> same fingerprint (coro is the key).
        assert compute_fingerprint(with_task) == compute_fingerprint(same_coro_diff_name)

        # Two empty watchdogs match.
        empty2 = _event(
            EventKind.WATCHDOG, self._wd(()), severity="warning"
        )
        assert compute_fingerprint(empty) == compute_fingerprint(empty2)


class TestFingerprintAnomaly:
    def test_fingerprint_anomaly_uses_type_only(self):
        """
        Given the 4 anomaly types,
        When fingerprints are computed,
        Then all 4 are distinct and depend only on anomaly_type.
        """
        types = ("memory_ceiling", "cpu_spike", "fds_ceiling", "threads_spike")
        fps = set()
        for t in types:
            p = AnomalyPayload(
                anomaly_type=t,  # type: ignore[arg-type]
                current=1.0,
                baseline=2.0,
                threshold_pct=50.0,
                window="5m",
                details={},
            )
            e = _event(EventKind.ANOMALY, p, severity="warning")
            fps.add(compute_fingerprint(e))
        assert len(fps) == 4

        # Same type, different values -> same fingerprint.
        p1 = AnomalyPayload(
            anomaly_type="rss_spike",
            current=100.0,
            baseline=50.0,
            threshold_pct=20.0,
            window="5m",
            details={"k": 1},
        )
        p2 = AnomalyPayload(
            anomaly_type="rss_spike",
            current=9999.0,
            baseline=1.0,
            threshold_pct=99.0,
            window="1m",
            details={"k": 2},
        )
        e1 = _event(EventKind.ANOMALY, p1, severity="warning")
        e2 = _event(EventKind.ANOMALY, p2, severity="warning")
        assert compute_fingerprint(e1) == compute_fingerprint(e2)


class TestFingerprintLifecycle:
    def test_fingerprint_lifecycle_returns_none(self):
        """
        Given a lifecycle event,
        When compute_fingerprint is called,
        Then it returns None (invariants D7, E1 — never dedup'd).
        """
        p = LifecyclePayload(phase="startup", reason="init")
        e = _event(EventKind.LIFECYCLE, p, severity=None)
        assert compute_fingerprint(e) is None


class TestFingerprintContract:
    def test_fingerprint_deterministic(self):
        """
        Given identical input,
        When compute_fingerprint is called multiple times,
        Then the output is identical (invariant E3).
        """
        frames = (
            _frame("a.py", 1, "f", is_user_code=True),
            _frame("b.py", 2, "g", is_user_code=True),
            _frame("c.py", 3, "h", is_user_code=True),
        )
        e = _event(EventKind.CRASH, _crash("OSError", "x", frames))
        assert compute_fingerprint(e) == compute_fingerprint(e)

    def test_fingerprint_length_6_hex(self):
        """
        Given any non-lifecycle event,
        When compute_fingerprint runs,
        Then it returns a 6-character lowercase hex string.
        """
        p = SlowCallPayload(
            func_qualname="x.y",
            duration_ms=1.0,
            threshold_ms=1.0,
            is_async=False,
            location=Location(file="x.py", line=1),
        )
        e = _event(EventKind.SLOW_CALL, p, severity="warning")
        fp = compute_fingerprint(e)
        assert isinstance(fp, str)
        assert HEX6_RE.match(fp) is not None

    @pytest.mark.parametrize(
        "kind_factory",
        [
            lambda: (
                EventKind.CRASH,
                CrashPayload(
                    exception_type="E",
                    message="m",
                    stack=(),
                    thread="t",
                    origin="sys_excepthook",
                ),
                "error",
                None,
            ),
            lambda: (
                EventKind.LIFECYCLE,
                LifecyclePayload(phase="shutdown", reason="clean_exit"),
                None,
                None,
            ),
        ],
    )
    def test_fingerprint_return_type_is_str_or_none(self, kind_factory):
        """
        Given any event kind,
        When compute_fingerprint runs,
        Then the result is either a str (6 hex) or None (lifecycle only).
        """
        kind, payload, severity, context = kind_factory()
        e = _event(kind, payload, severity=severity, context=context)
        fp = compute_fingerprint(e)
        assert fp is None or (isinstance(fp, str) and HEX6_RE.match(fp))
