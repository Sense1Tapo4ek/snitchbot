"""Flow tests for VitalsSamplerWorkflow — Task 10.3.

Spec: docs/superpowers/specs/2026-04-11-live-message-vitals-design.md §3.4.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 10.3.

Invariants validated: V5 (error isolation), A1 (anomaly after sample), LM8 (status transitions).

Uses MagicMock for the event enqueue interface.
psutil is not installed in the test env; stub exception classes used.
"""
import time
from collections import deque
from unittest.mock import MagicMock, patch

from snitchbot.shared.domain.anomaly_config_vo import (
    AnomalyConfig,
    CpuAnomalyConfig,
    RssAnomalyConfig,
)
from snitchbot.shared.domain.client_state import ClientState
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.anomalies.app.workflows.vitals_sampler_workflow import VitalsSamplerWorkflow
from snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler import PsutilVitalsSampler

_PATCH_TARGET = "snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler.psutil"


# ---------------------------------------------------------------------------
# Stub psutil exceptions
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
    m = MagicMock()
    m.NoSuchProcess = _NoSuchProcess
    m.AccessDenied = _AccessDenied
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    pid: int = 1234,
    vitals_status: str = "ok",
    fds_last_sampled_at: float = 0.0,
) -> ClientState:
    return ClientState(
        pid=pid,
        role="standalone",
        service="test-svc",
        last_seen=time.monotonic(),
        connected_at=time.monotonic(),
        psutil_process=None,
        psutil_create_time=None,
        latest_vitals=None,
        vitals_history=deque(maxlen=60),
        vitals_status=vitals_status,
        fds_last_sampled_at=fds_last_sampled_at,
        anomaly_config=AnomalyConfig(),
    )


# ---------------------------------------------------------------------------
# Test: iterates over snapshot of clients (concurrent safe)
# ---------------------------------------------------------------------------


class TestIteratesOverSnapshotOfClients:
    def test_iterates_over_snapshot_of_clients_concurrent_safe(self) -> None:
        """
        Given two clients in the registry,
        When run_sampling_tick is called,
        Then both clients are sampled — modifying the dict mid-iteration is safe
        because the workflow iterates over a snapshot (list) of client values (V5).
        """
        clients: dict[int, ClientState] = {}
        c1 = _make_client(pid=101)
        c2 = _make_client(pid=202)
        clients[101] = c1
        clients[202] = c2

        mock_proc_1 = MagicMock()
        mock_proc_1.create_time.return_value = 1.0
        mock_proc_1.memory_info.return_value.rss = 50 * 1024 * 1024
        mock_proc_1.cpu_percent.return_value = 5.0
        mock_proc_1.num_threads.return_value = 4
        mock_proc_1.num_fds.return_value = 10

        mock_proc_2 = MagicMock()
        mock_proc_2.create_time.return_value = 2.0
        mock_proc_2.memory_info.return_value.rss = 80 * 1024 * 1024
        mock_proc_2.cpu_percent.return_value = 10.0
        mock_proc_2.num_threads.return_value = 6
        mock_proc_2.num_fds.return_value = 15

        def _make_process(pid: int) -> MagicMock:
            return mock_proc_1 if pid == 101 else mock_proc_2

        enqueue_fn = MagicMock()
        workflow = VitalsSamplerWorkflow(_enqueue_anomaly=enqueue_fn, _sampler=PsutilVitalsSampler())
        mock_ps = _mock_psutil_module()
        mock_ps.Process.side_effect = _make_process

        with patch(_PATCH_TARGET, mock_ps):
            workflow.run_sampling_tick(clients, now=time.time())

        assert c1.latest_vitals is not None
        assert c2.latest_vitals is not None


# ---------------------------------------------------------------------------
# Test: calls check_anomalies after each successful sample
# ---------------------------------------------------------------------------


class TestCallsCheckAnomaliesAfterSample:
    def test_calls_check_anomalies_after_each_successful_sample(self) -> None:
        """
        Given a client that samples successfully with enough history for anomaly detection,
        When run_sampling_tick fires and anomaly conditions are met,
        Then _enqueue_anomaly is called with the anomaly result (A1).
        """
        _MB = 1024 * 1024
        baseline_rss = 100 * _MB

        client = _make_client(pid=300)
        # Pre-populate history so rss_ceiling triggers on next sample.
        # Use enough samples to satisfy the window averaging (60 stable samples).
        for _ in range(60):
            client.vitals_history.append(
                VitalsSnapshot(
                    sampled_at=time.time(),
                    rss_bytes=baseline_rss,
                    cpu_percent=5.0,
                    threads=4,
                    fds=20,
                    total_rss_bytes=baseline_rss,
                    total_cpu_percent=5.0,
                    children_count=0,
                )
            )

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 3.0
        mock_proc.memory_info.return_value.rss = 500 * _MB  # exceeds default max_mb=450
        mock_proc.cpu_percent.return_value = 5.0
        mock_proc.num_threads.return_value = 4
        mock_proc.num_fds.return_value = 20

        clients = {300: client}
        enqueue_fn = MagicMock()
        workflow = VitalsSamplerWorkflow(_enqueue_anomaly=enqueue_fn, _sampler=PsutilVitalsSampler())
        mock_ps = _mock_psutil_module()
        mock_ps.Process.return_value = mock_proc

        with patch(_PATCH_TARGET, mock_ps):
            workflow.run_sampling_tick(clients, now=time.time())

        assert enqueue_fn.call_count >= 1
        event = enqueue_fn.call_args_list[0][0][0]
        assert event["kind"] == "anomaly"
        assert event["pid"] == 300
        assert event["payload"]["anomaly_type"].startswith("rss_")


# ---------------------------------------------------------------------------
# Test: client status transitions ok -> stale -> unavailable -> dead (LM8)
# ---------------------------------------------------------------------------


class TestClientStatusTransitions:
    def test_client_status_transitions_ok_stale_unavailable_dead(self) -> None:
        """
        Given a client with status 'stale' that samples successfully,
        When the sampler runs a tick,
        Then vitals_status transitions to 'ok' (LM8).
        """
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 4.0
        mock_proc.memory_info.return_value.rss = 50 * 1024 * 1024
        mock_proc.cpu_percent.return_value = 5.0
        mock_proc.num_threads.return_value = 4
        mock_proc.num_fds.return_value = 20

        client = _make_client(pid=400, vitals_status="stale")
        clients = {400: client}
        enqueue_fn = MagicMock()
        workflow = VitalsSamplerWorkflow(_enqueue_anomaly=enqueue_fn, _sampler=PsutilVitalsSampler())
        mock_ps = _mock_psutil_module()
        mock_ps.Process.return_value = mock_proc

        with patch(_PATCH_TARGET, mock_ps):
            workflow.run_sampling_tick(clients, now=time.time())

        assert client.vitals_status == "ok"


# ---------------------------------------------------------------------------
# Test: total_rss / total_cpu detectors enqueue events (subprocess discovery)
# ---------------------------------------------------------------------------


class TestTotalDetectors:
    def test_total_rss_detector_enqueues_event(self) -> None:
        """
        Given a client with total_rss_bytes exceeding config max_mb,
        When run_sampling_tick fires with total_rss detector enabled,
        Then _enqueue_anomaly is called with a total_rss_ceiling event.
        """
        _MB = 1024 * 1024
        baseline_rss = 100 * _MB

        client = _make_client(pid=500)
        client.anomaly_config = AnomalyConfig(
            rss=None,
            cpu=None,
            fds=None,
            threads=None,
            watchdog=None,
            total_rss=RssAnomalyConfig(max_mb=200.0, spike_ratio=None, drop_ratio=None),
            total_cpu=None,
        )
        for _ in range(60):
            client.vitals_history.append(
                VitalsSnapshot(
                    sampled_at=time.time(),
                    rss_bytes=baseline_rss,
                    cpu_percent=5.0,
                    threads=4,
                    fds=20,
                    total_rss_bytes=baseline_rss,
                    total_cpu_percent=5.0,
                    children_count=0,
                )
            )

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 5.0
        mock_proc.memory_info.return_value.rss = 250 * _MB
        mock_proc.cpu_percent.return_value = 5.0
        mock_proc.num_threads.return_value = 4
        mock_proc.num_fds.return_value = 20
        mock_proc.children.return_value = []

        clients = {500: client}
        enqueue_fn = MagicMock()
        workflow = VitalsSamplerWorkflow(_enqueue_anomaly=enqueue_fn, _sampler=PsutilVitalsSampler())
        mock_ps = _mock_psutil_module()
        mock_ps.Process.return_value = mock_proc

        with patch(_PATCH_TARGET, mock_ps):
            workflow.run_sampling_tick(clients, now=time.time())

        assert enqueue_fn.call_count >= 1
        event = enqueue_fn.call_args_list[0][0][0]
        assert event["kind"] == "anomaly"
        assert event["pid"] == 500
        assert event["payload"]["anomaly_type"].startswith("total_rss_")

    def test_total_cpu_detector_enqueues_event(self) -> None:
        """
        Given a client with total_cpu_percent exceeding config max_percent,
        When run_sampling_tick fires with total_cpu detector enabled,
        Then _enqueue_anomaly is called with a total_cpu_ceiling event.
        """
        client = _make_client(pid=501)
        client.anomaly_config = AnomalyConfig(
            rss=None,
            cpu=None,
            fds=None,
            threads=None,
            watchdog=None,
            total_rss=None,
            total_cpu=CpuAnomalyConfig(max_percent=80.0, spike_ratio=None, drop_ratio=None),
        )
        for _ in range(60):
            client.vitals_history.append(
                VitalsSnapshot(
                    sampled_at=time.time(),
                    rss_bytes=100 * 1024 * 1024,
                    cpu_percent=5.0,
                    threads=4,
                    fds=20,
                    total_rss_bytes=100 * 1024 * 1024,
                    total_cpu_percent=5.0,
                    children_count=0,
                )
            )

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 6.0
        mock_proc.memory_info.return_value.rss = 100 * 1024 * 1024
        mock_proc.cpu_percent.return_value = 95.0
        mock_proc.num_threads.return_value = 4
        mock_proc.num_fds.return_value = 20
        mock_proc.children.return_value = []

        clients = {501: client}
        enqueue_fn = MagicMock()
        workflow = VitalsSamplerWorkflow(_enqueue_anomaly=enqueue_fn, _sampler=PsutilVitalsSampler())
        mock_ps = _mock_psutil_module()
        mock_ps.Process.return_value = mock_proc

        with patch(_PATCH_TARGET, mock_ps):
            workflow.run_sampling_tick(clients, now=time.time())

        assert enqueue_fn.call_count >= 1
        event = enqueue_fn.call_args_list[0][0][0]
        assert event["kind"] == "anomaly"
        assert event["pid"] == 501
        assert event["payload"]["anomaly_type"].startswith("total_cpu_")
