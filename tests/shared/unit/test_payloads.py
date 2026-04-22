"""Unit tests for the six kind-specific payload VOs.

Spec: ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §4.1–4.6.
Additional spec: ``docs/superpowers/specs/2026-04-11-logging-integration-design.md``
invariant L6 — ``CustomPayload.source`` field semantics.

Invariants covered: E1 (envelope shape), E7 (type constraints), L6 (custom source).
"""
from dataclasses import FrozenInstanceError, fields

import pytest

from snitchbot.shared.domain import (
    AnomalyPayload,
    Caller,
    CrashPayload,
    CustomPayload,
    LifecyclePayload,
    Location,
    SlowCallPayload,
    StackFrame,
    StuckTask,
    WatchdogPayload,
)


def _make_frame(**overrides: object) -> StackFrame:
    base: dict[str, object] = dict(
        file="app/db/pool.py", line=47, func="acquire",
        code="conn = await self._pool.get()", is_user_code=True,
    )
    base.update(overrides)
    return StackFrame(**base)  # type: ignore[arg-type]


def _make_crash(**overrides: object) -> CrashPayload:
    base: dict[str, object] = dict(
        exception_type="DatabaseConnectionError",
        message="connection refused",
        stack=(_make_frame(),),
        thread="MainThread",
        origin="sys_excepthook",
    )
    base.update(overrides)
    return CrashPayload(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CrashPayload + StackFrame (spec §4.1)
# ---------------------------------------------------------------------------


class TestCrashPayload:
    def test_crash_payload_shape(self) -> None:
        """
        Given valid crash fields,
        When constructing CrashPayload,
        Then all fields are accessible. (E1)
        """
        payload = _make_crash()
        assert payload.exception_type == "DatabaseConnectionError"
        assert payload.message == "connection refused"
        assert isinstance(payload.stack, tuple)
        assert payload.thread == "MainThread"
        assert payload.origin == "sys_excepthook"

    def test_crash_payload_frozen(self) -> None:
        """
        Given a CrashPayload,
        When mutating a field,
        Then FrozenInstanceError is raised.
        """
        payload = _make_crash()
        with pytest.raises(FrozenInstanceError):
            payload.exception_type = "X"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "origin",
        ["sys_excepthook", "threading_excepthook", "asyncio_handler", "signal_handler"],
    )
    def test_crash_origin_accepts_valid_values(self, origin: str) -> None:
        """
        Given each of the four valid origins,
        When constructing CrashPayload,
        Then construction succeeds.
        """
        payload = _make_crash(origin=origin)
        assert payload.origin == origin


class TestStackFrame:
    def test_stack_frame_shape(self) -> None:
        """
        Given file, line, func, code, is_user_code,
        When constructing StackFrame,
        Then all fields are set; code may be None. (§4.1)
        """
        f1 = StackFrame(file="a.py", line=1, func="fn", code="x = 1", is_user_code=True)
        f2 = StackFrame(file="b.py", line=2, func="gn", code=None, is_user_code=False)
        assert f1.code == "x = 1"
        assert f1.is_user_code is True
        assert f2.code is None
        assert f2.is_user_code is False

    def test_stack_frame_frozen(self) -> None:
        frame = StackFrame(file="a.py", line=1, func="fn", code=None, is_user_code=True)
        with pytest.raises(FrozenInstanceError):
            frame.line = 2  # type: ignore[misc]

    def test_stack_frame_is_user_code_required(self) -> None:
        """
        Given is_user_code omitted,
        When constructing StackFrame,
        Then TypeError is raised (required field, no default).
        """
        with pytest.raises(TypeError):
            StackFrame(file="a.py", line=1, func="fn", code=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# CustomPayload + Caller (spec §4.2, L6)
# ---------------------------------------------------------------------------


class TestCaller:
    def test_caller_shape(self) -> None:
        """
        Given file, line, func,
        When constructing Caller,
        Then fields are retained. (§4.2)
        """
        c = Caller(file="app/views.py", line=42, func="handle_request")
        assert c.file == "app/views.py"
        assert c.line == 42
        assert c.func == "handle_request"

    def test_caller_frozen(self) -> None:
        c = Caller(file="x.py", line=1, func="f")
        with pytest.raises(FrozenInstanceError):
            c.file = "y.py"  # type: ignore[misc]


class TestCustomPayload:
    def test_custom_payload_shape(self) -> None:
        """
        Given text, extras, exception, source, caller,
        When constructing CustomPayload,
        Then fields are retained. (E1)
        """
        caller = Caller(file="x.py", line=10, func="notify_caller")
        payload = CustomPayload(
            text="hello", extras={"k": "v"}, exception=None,
            source="notify", caller=caller,
        )
        assert payload.text == "hello"
        assert payload.extras == {"k": "v"}
        assert payload.caller is not None
        assert payload.caller.file == "x.py"

    @pytest.mark.parametrize("source", ["notify", "logging", "structlog"])
    def test_custom_payload_accepts_source_field(self, source: str) -> None:
        """
        Given source in {notify, logging, structlog},
        When constructing CustomPayload,
        Then construction succeeds. (L6)
        """
        payload = CustomPayload(text="x", extras=None, exception=None, source=source)  # type: ignore[arg-type]
        assert payload.source == source

    def test_custom_payload_source_none_default(self) -> None:
        """
        Given source omitted,
        When constructing CustomPayload,
        Then source is None (interpreted downstream as 'notify'). (L6)
        """
        payload = CustomPayload(text="x", extras=None, exception=None)
        assert payload.source is None

    def test_custom_payload_caller_none_default(self) -> None:
        """
        Given caller omitted,
        When constructing CustomPayload,
        Then caller is None.
        """
        payload = CustomPayload(text="x", extras=None, exception=None)
        assert payload.caller is None


# ---------------------------------------------------------------------------
# SlowCallPayload + Location (spec §4.3)
# ---------------------------------------------------------------------------


class TestLocation:
    def test_location_shape(self) -> None:
        loc = Location(file="app/slow.py", line=99)
        assert loc.file == "app/slow.py"
        assert loc.line == 99

    def test_location_frozen(self) -> None:
        loc = Location(file="x.py", line=1)
        with pytest.raises(FrozenInstanceError):
            loc.line = 2  # type: ignore[misc]


class TestSlowCallPayload:
    def test_slow_call_payload_shape(self) -> None:
        """
        Given required slow_call fields per spec §4.3,
        When constructing SlowCallPayload,
        Then fields are retained. (E1)
        """
        payload = SlowCallPayload(
            func_qualname="pkg.mod.fn",
            duration_ms=1843.0,
            threshold_ms=1000.0,
            is_async=True,
            location=Location(file="pkg/mod.py", line=42),
        )
        assert payload.func_qualname == "pkg.mod.fn"
        assert payload.duration_ms == 1843.0
        assert payload.threshold_ms == 1000.0
        assert payload.is_async is True
        assert payload.location.file == "pkg/mod.py"

    @pytest.mark.parametrize("is_async", [True, False])
    def test_slow_call_is_async_bool(self, is_async: bool) -> None:
        """
        Given is_async as bool (spec §4.3),
        When constructing SlowCallPayload,
        Then construction succeeds.
        """
        payload = SlowCallPayload(
            func_qualname="f", duration_ms=1.0, threshold_ms=0.5,
            is_async=is_async, location=Location(file="f.py", line=1),
        )
        assert payload.is_async is is_async

    def test_slow_call_no_args_preview(self) -> None:
        """Spec §13 explicitly forbids args_summary/previews."""
        assert not hasattr(SlowCallPayload, "args_preview")
        assert not hasattr(SlowCallPayload, "kwargs_preview")


# ---------------------------------------------------------------------------
# WatchdogPayload + StuckTask (spec §4.4)
# ---------------------------------------------------------------------------


class TestWatchdogPayload:
    def test_watchdog_payload_shape(self) -> None:
        """
        Given spec §4.4 fields: block_duration_ms, threshold_ms, loop_id, stuck_tasks,
        When constructing WatchdogPayload,
        Then fields are retained. (E1)
        """
        stuck = (StuckTask(name="Task-42", coro="app.worker.process", stack=("line1",)),)
        payload = WatchdogPayload(
            block_duration_ms=847.0,
            threshold_ms=500.0,
            loop_id="main",
            stuck_tasks=stuck,
        )
        assert payload.block_duration_ms == 847.0
        assert payload.threshold_ms == 500.0
        assert payload.loop_id == "main"
        assert len(payload.stuck_tasks) == 1

    def test_watchdog_empty_stuck_tasks(self) -> None:
        payload = WatchdogPayload(
            block_duration_ms=600.0, threshold_ms=500.0,
            loop_id="main", stuck_tasks=(),
        )
        assert payload.stuck_tasks == ()


class TestStuckTask:
    def test_stuck_task_shape(self) -> None:
        """
        Given name, coro, stack per spec §4.4,
        When constructing StuckTask,
        Then fields are retained.
        """
        task = StuckTask(name="Task-1", coro="app.handler.run", stack=("frame1", "frame2"))
        assert task.name == "Task-1"
        assert task.coro == "app.handler.run"
        assert task.stack == ("frame1", "frame2")

    def test_stuck_task_frozen(self) -> None:
        task = StuckTask(name="T", coro="c", stack=())
        with pytest.raises(FrozenInstanceError):
            task.name = "X"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AnomalyPayload (spec §4.5)
# ---------------------------------------------------------------------------


class TestAnomalyPayload:
    def test_anomaly_payload_shape(self) -> None:
        """
        Given spec §4.5 fields,
        When constructing AnomalyPayload,
        Then fields are retained. (E1)
        """
        payload = AnomalyPayload(
            anomaly_type="rss_spike",
            current=256_000_000.0,
            baseline=120_000_000.0,
            threshold_pct=50.0,
            window="1m",
            details={"peak_mb": 256},
        )
        assert payload.anomaly_type == "rss_spike"
        assert payload.current == 256_000_000.0
        assert payload.baseline == 120_000_000.0
        assert payload.threshold_pct == 50.0
        assert payload.window == "1m"

    @pytest.mark.parametrize(
        "atype", [
            "memory_ceiling", "rss_spike", "memory_drop",
            "cpu_ceiling", "cpu_spike", "cpu_drop",
            "fds_ceiling", "fds_spike", "fds_drop",
            "threads_ceiling", "threads_spike", "threads_drop",
        ]
    )
    def test_anomaly_type_all_four_accepted(self, atype: str) -> None:
        """
        Given each of the four anomaly types,
        When constructing AnomalyPayload,
        Then construction succeeds.
        """
        payload = AnomalyPayload(
            anomaly_type=atype, current=1.0, baseline=0.5,  # type: ignore[arg-type]
            threshold_pct=50.0, window="1m", details={},
        )
        assert payload.anomaly_type == atype


# ---------------------------------------------------------------------------
# LifecyclePayload (spec §4.6)
# ---------------------------------------------------------------------------


class TestLifecyclePayload:
    @pytest.mark.parametrize("phase", ["startup", "shutdown"])
    def test_lifecycle_payload_phase(self, phase: str) -> None:
        """
        Given phase in {startup, shutdown},
        When constructing LifecyclePayload,
        Then construction succeeds. (E2)
        """
        payload = LifecyclePayload(phase=phase, reason="init")  # type: ignore[arg-type]
        assert payload.phase == phase

    @pytest.mark.parametrize("reason", ["init", "sigterm", "crash", "clean_exit"])
    def test_lifecycle_payload_reason_four_values(self, reason: str) -> None:
        """
        Given each of the four valid reasons (spec §4.6),
        When constructing LifecyclePayload,
        Then construction succeeds.
        """
        payload = LifecyclePayload(phase="shutdown", reason=reason)  # type: ignore[arg-type]
        assert payload.reason == reason

    def test_lifecycle_exit_code_optional(self) -> None:
        """exit_code defaults to None, can be set to an int."""
        p1 = LifecyclePayload(phase="shutdown", reason="crash")
        assert p1.exit_code is None
        p2 = LifecyclePayload(phase="shutdown", reason="crash", exit_code=1)
        assert p2.exit_code == 1


# ---------------------------------------------------------------------------
# Parametrized frozen + slots checks across all six payloads
# ---------------------------------------------------------------------------


ALL_PAYLOAD_INSTANCES = [
    pytest.param(
        _make_crash(), "exception_type", id="CrashPayload",
    ),
    pytest.param(
        CustomPayload(text="t", extras=None, exception=None),
        "text", id="CustomPayload",
    ),
    pytest.param(
        SlowCallPayload(
            func_qualname="f", duration_ms=1.0, threshold_ms=0.5,
            is_async=False, location=Location(file="f.py", line=1),
        ),
        "func_qualname", id="SlowCallPayload",
    ),
    pytest.param(
        WatchdogPayload(
            block_duration_ms=0.0, threshold_ms=500.0,
            loop_id="main", stuck_tasks=(),
        ),
        "block_duration_ms", id="WatchdogPayload",
    ),
    pytest.param(
        AnomalyPayload(
            anomaly_type="rss_spike", current=1.0, baseline=0.5,
            threshold_pct=50.0, window="1m", details={},
        ),
        "anomaly_type", id="AnomalyPayload",
    ),
    pytest.param(
        LifecyclePayload(phase="startup", reason="init"),
        "phase", id="LifecyclePayload",
    ),
]


@pytest.mark.parametrize("instance,attr", ALL_PAYLOAD_INSTANCES)
def test_all_payloads_frozen(instance: object, attr: str) -> None:
    """
    Given any payload instance,
    When mutating a field,
    Then FrozenInstanceError is raised. (E1 — immutability)
    """
    with pytest.raises(FrozenInstanceError):
        setattr(instance, attr, "mutated")


ALL_PAYLOAD_CLASSES = [
    CrashPayload, CustomPayload, SlowCallPayload,
    WatchdogPayload, AnomalyPayload, LifecyclePayload,
]


@pytest.mark.parametrize("cls", ALL_PAYLOAD_CLASSES, ids=lambda c: c.__name__)
def test_all_payloads_slots_defined(cls: type) -> None:
    """
    Given any payload class,
    When inspecting __slots__,
    Then slots are defined.
    """
    assert hasattr(cls, "__slots__")
    assert len(fields(cls)) >= 1  # type: ignore[arg-type]
