"""Unit tests for PsutilVitalsSampler — Task 10.1.

Spec: docs/superpowers/specs/2026-04-11-live-message-vitals-design.md §3.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 10.1.

Invariants validated: V1–V10.

psutil.Process is mocked throughout — unit tests never touch the OS.
psutil is a sidecar-only optional dep not installed in the test env;
stub exception classes are used in its place.
"""
import time
from collections import deque
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from snitchbot.shared.constants import VITALS_SAMPLE_SEC
from snitchbot.shared.domain.client_state import ClientState
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler import PsutilVitalsSampler

# ---------------------------------------------------------------------------
# Stub psutil exceptions (psutil is not installed in the test environment)
# ---------------------------------------------------------------------------


class _NoSuchProcess(Exception):
    def __init__(self, pid: int = 0, **kw: object) -> None:
        self.pid = pid
        super().__init__(f"NoSuchProcess: pid={pid}")


class _AccessDenied(Exception):
    def __init__(self, pid: int = 0, **kw: object) -> None:
        self.pid = pid
        super().__init__(f"AccessDenied: pid={pid}")


def _mock_psutil_module() -> MagicMock:
    """Return a MagicMock that stands in for the ``psutil`` module."""
    m = MagicMock()
    m.NoSuchProcess = _NoSuchProcess
    m.AccessDenied = _AccessDenied
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    pid: int = 1234,
    role: str = "standalone",
    service: str = "test-svc",
    fds_last_sampled_at: float = 0.0,
    latest_vitals: VitalsSnapshot | None = None,
    psutil_process: object | None = None,
    psutil_create_time: float | None = None,
    vitals_history: deque | None = None,
    vitals_status: Literal["ok", "stale", "unavailable", "dead"] = "ok",
) -> ClientState:
    return ClientState(
        pid=pid,
        role=role,
        service=service,
        last_seen=time.monotonic(),
        connected_at=time.monotonic(),
        psutil_process=psutil_process,
        psutil_create_time=psutil_create_time,
        latest_vitals=latest_vitals,
        vitals_history=vitals_history if vitals_history is not None else deque(maxlen=60),
        vitals_status=vitals_status,
        fds_last_sampled_at=fds_last_sampled_at,
    )


def _make_mock_process(
    rss: int = 50 * 1024 * 1024,
    cpu: float = 10.0,
    threads: int = 4,
    fds: int = 20,
    create_time: float = 12345.0,
) -> MagicMock:
    proc = MagicMock()
    proc.memory_info.return_value.rss = rss
    proc.cpu_percent.return_value = cpu
    proc.num_threads.return_value = threads
    proc.num_fds.return_value = fds
    proc.create_time.return_value = create_time
    return proc


_PATCH_TARGET = "snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler.psutil"


# ---------------------------------------------------------------------------
# V3: Process object cached per client for correct cpu_percent
# ---------------------------------------------------------------------------


class TestProcessCachedPerClient:
    def test_process_cached_per_client_for_cpu_percent(self) -> None:
        """
        Given a client with no psutil_process,
        When sample_one_client is called twice,
        Then psutil.Process is constructed only once — same object reused (V3).
        """
        mock_proc = _make_mock_process()
        client = _make_client(fds_last_sampled_at=0.0)
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()
        mock_ps.Process.return_value = mock_proc

        with patch(_PATCH_TARGET, mock_ps):
            now = time.time()
            sampler.sample_one_client(client, now=now)
            sampler.sample_one_client(client, now=now + VITALS_SAMPLE_SEC)

        assert mock_ps.Process.call_count == 1
        assert client.psutil_process is mock_proc


# ---------------------------------------------------------------------------
# V4: PID reuse guard via create_time
# ---------------------------------------------------------------------------


class TestPidReuseGuard:
    def test_pid_reuse_guard_via_create_time_raises_NoSuchProcess(self) -> None:
        """
        Given a cached process whose create_time changes (PID reuse),
        When sample_one_client is called again,
        Then NoSuchProcess is raised (V4).
        """
        original_create_time = 1000.0
        mock_proc = _make_mock_process(create_time=original_create_time)
        client = _make_client(
            psutil_process=mock_proc,
            psutil_create_time=original_create_time,
            fds_last_sampled_at=0.0,
        )
        # Simulate PID reuse — create_time changed
        mock_proc.create_time.return_value = 9999.0

        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            with pytest.raises(_NoSuchProcess):
                sampler.sample_one_client(client, now=time.time())


# ---------------------------------------------------------------------------
# V6: NoSuchProcess marks client dead
# ---------------------------------------------------------------------------


class TestNoSuchProcessMarksDead:
    def test_no_such_process_marks_client_dead(self) -> None:
        """
        Given a client whose process no longer exists,
        When the sampler loop encounters it,
        Then vitals_status is set to 'dead' (V6).
        """
        client = _make_client(pid=42)
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()
        mock_ps.Process.side_effect = _NoSuchProcess(pid=42)

        with patch(_PATCH_TARGET, mock_ps):
            sampler.sample_into_state(client, now=time.time())

        assert client.vitals_status == "dead"


# ---------------------------------------------------------------------------
# V7: AccessDenied (whole process) -> unavailable
# ---------------------------------------------------------------------------


class TestAccessDeniedWholeProcess:
    def test_access_denied_whole_process_marks_unavailable(self) -> None:
        """
        Given a client for which psutil.AccessDenied is raised on memory_info,
        When the sampler processes that client,
        Then vitals_status is set to 'unavailable' (V7).
        """
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 999.0
        mock_proc.memory_info.side_effect = _AccessDenied(pid=99)

        client = _make_client(
            pid=99,
            psutil_process=mock_proc,
            psutil_create_time=999.0,
            fds_last_sampled_at=0.0,
        )
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            sampler.sample_into_state(client, now=time.time())

        assert client.vitals_status == "unavailable"


# ---------------------------------------------------------------------------
# V8: AccessDenied on num_fds only -> fds=None, client not unavailable
# ---------------------------------------------------------------------------


class TestFdsAccessDeniedPerMetric:
    def test_num_fds_access_denied_returns_None_metric_not_whole_client(self) -> None:
        """
        Given a client where num_fds() raises AccessDenied (macOS M1 edge),
        When sample_one_client is called (FDs due for sampling),
        Then fds=None in the snapshot but other metrics are intact (V8).
        """
        mock_proc = _make_mock_process(create_time=500.0)
        mock_proc.num_fds.side_effect = _AccessDenied(pid=77)

        client = _make_client(
            pid=77,
            psutil_process=mock_proc,
            psutil_create_time=500.0,
            fds_last_sampled_at=0.0,  # FDs due for sampling
        )
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            snapshot = sampler.sample_one_client(client, now=time.time())

        assert snapshot.fds is None
        assert snapshot.rss_bytes > 0
        assert snapshot.cpu_percent >= 0
        assert snapshot.threads > 0
        assert client.vitals_status != "unavailable"


# ---------------------------------------------------------------------------
# V9: FDs sampled every 15s, not 5s
# ---------------------------------------------------------------------------


class TestFdsSamplingInterval:
    def test_fds_sampled_every_15s_not_5s(self) -> None:
        """
        Given a client where fds_last_sampled_at is 5s ago (not yet 15s),
        When sample_one_client is called,
        Then num_fds() is NOT called, previous fds value is kept (V9).
        """
        now = time.time()
        prev_snapshot = VitalsSnapshot(
            sampled_at=now - 5,
            rss_bytes=1_000_000,
            cpu_percent=5.0,
            threads=2,
            fds=10,
            total_rss_bytes=1_000_000,
            total_cpu_percent=5.0,
            children_count=0,
        )
        mock_proc = _make_mock_process(create_time=700.0)
        client = _make_client(
            psutil_process=mock_proc,
            psutil_create_time=700.0,
            fds_last_sampled_at=now - 5,  # only 5s ago, below 15s threshold
            latest_vitals=prev_snapshot,
        )
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            snapshot = sampler.sample_one_client(client, now=now)

        mock_proc.num_fds.assert_not_called()
        assert snapshot.fds == 10  # kept from previous snapshot


# ---------------------------------------------------------------------------
# V1: Non-FD metrics sampled every 5s
# ---------------------------------------------------------------------------


class TestNonFdsSamplingFrequency:
    def test_non_fds_sampled_every_5s(self) -> None:
        """
        Given a client with a cached process,
        When sample_one_client is called,
        Then memory_info, cpu_percent, and num_threads are always called (V1).
        """
        mock_proc = _make_mock_process(create_time=800.0)
        client = _make_client(
            psutil_process=mock_proc,
            psutil_create_time=800.0,
            fds_last_sampled_at=time.time(),  # FDs not due
        )
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            sampler.sample_one_client(client, now=time.time())

        mock_proc.memory_info.assert_called_once()
        mock_proc.cpu_percent.assert_called_once_with(interval=None)
        mock_proc.num_threads.assert_called_once()


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------


class TestSampleOneClientReturnsSnapshot:
    def test_sample_one_client_returns_snapshot_with_rss_cpu_threads_fds(self) -> None:
        """
        Given a healthy process,
        When sample_one_client is called with FDs due,
        Then the returned VitalsSnapshot has all four metrics set.
        """
        mock_proc = _make_mock_process(
            rss=80 * 1024 * 1024,
            cpu=15.0,
            threads=8,
            fds=24,
            create_time=900.0,
        )
        client = _make_client(
            psutil_process=mock_proc,
            psutil_create_time=900.0,
            fds_last_sampled_at=0.0,  # FDs due
        )
        sampler = PsutilVitalsSampler()
        now = time.time()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            snapshot = sampler.sample_one_client(client, now=now)

        assert snapshot.rss_bytes == 80 * 1024 * 1024
        assert snapshot.cpu_percent == 15.0
        assert snapshot.threads == 8
        assert snapshot.fds == 24
        assert snapshot.sampled_at == now


# ---------------------------------------------------------------------------
# V5: Error on one client does not break loop
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    def test_error_on_one_client_does_not_break_loop(self) -> None:
        """
        Given two clients where the first raises an unexpected error,
        When the sampler runs a full tick,
        Then the second client is still sampled successfully (V5).
        """
        bad_proc = MagicMock()
        bad_proc.create_time.return_value = 1.0
        bad_proc.memory_info.side_effect = RuntimeError("unexpected!")

        good_proc = _make_mock_process(create_time=2.0)

        bad_client = _make_client(
            pid=100,
            psutil_process=bad_proc,
            psutil_create_time=1.0,
            fds_last_sampled_at=0.0,
        )
        good_client = _make_client(
            pid=200,
            psutil_process=good_proc,
            psutil_create_time=2.0,
            fds_last_sampled_at=0.0,
        )
        clients = {100: bad_client, 200: good_client}

        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            sampler.run_sampling_tick(clients, now=time.time())

        assert good_client.latest_vitals is not None
        assert good_client.vitals_status == "ok"


# ---------------------------------------------------------------------------
# V10: sleep_remaining anti-drift
# ---------------------------------------------------------------------------


class TestSleepRemaining:
    def test_sleep_remaining_does_not_drift(self) -> None:
        """
        Given that the sampler tick took elapsed seconds,
        When compute_sleep_remaining is called,
        Then it returns max(0, VITALS_SAMPLE_SEC - elapsed) (V10).
        """
        sampler = PsutilVitalsSampler()
        assert sampler.compute_sleep_remaining(elapsed=1.0) == pytest.approx(
            VITALS_SAMPLE_SEC - 1.0, abs=1e-6
        )
        assert sampler.compute_sleep_remaining(elapsed=VITALS_SAMPLE_SEC + 1.0) == 0.0


# ---------------------------------------------------------------------------
# V2: History deque maxlen=60
# ---------------------------------------------------------------------------


class TestHistoryDeque:
    def test_snapshot_appended_to_history_deque_maxlen_60(self) -> None:
        """
        Given a client with a deque(maxlen=60),
        When 61 snapshots are sampled,
        Then the deque contains at most 60 entries (V2).
        """
        mock_proc = _make_mock_process(create_time=111.0)
        history: deque[VitalsSnapshot] = deque(maxlen=60)
        client = _make_client(
            psutil_process=mock_proc,
            psutil_create_time=111.0,
            fds_last_sampled_at=0.0,
            vitals_history=history,
        )
        sampler = PsutilVitalsSampler()
        mock_ps = _mock_psutil_module()

        with patch(_PATCH_TARGET, mock_ps):
            base_now = time.time()
            for i in range(61):
                now = base_now + i * VITALS_SAMPLE_SEC
                client.fds_last_sampled_at = 0.0  # make FDs due every time
                sampler.sample_one_client(client, now=now)

        assert len(client.vitals_history) == 60
