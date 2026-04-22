"""Unit tests for v2 anomaly detectors — unified 3-mode model.

All detectors are pure functions (stdlib only). No mocks needed.
Tests cover: ceiling, spike, drop modes for each metric,
combined triggering, None-disabled modes, insufficient history.
"""
import time
from collections import deque

import pytest

from snitchbot.shared.domain.anomaly_config_vo import (
    CpuAnomalyConfig,
    FdAnomalyConfig,
    RssAnomalyConfig,
    ThreadAnomalyConfig,
)
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.anomalies.domain.services import (
    check_cpu,
    check_fds,
    check_rss,
    check_threads,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MB = 1024 * 1024


def _snap(
    rss_bytes: int = 100 * _MB,
    cpu_percent: float = 10.0,
    threads: int = 4,
    fds: int | None = 20,
    offset: float = 0.0,
) -> VitalsSnapshot:
    return VitalsSnapshot(
        sampled_at=time.time() + offset,
        rss_bytes=rss_bytes,
        cpu_percent=cpu_percent,
        threads=threads,
        fds=fds,
    )


def _history(*snaps: VitalsSnapshot, maxlen: int = 600) -> deque:
    d: deque = deque(maxlen=maxlen)
    d.extend(snaps)
    return d


def _stable_history(n: int = 60, **kwargs) -> deque:
    """Build a stable history of n identical snapshots."""
    return _history(*[_snap(**kwargs) for _ in range(n)])


# ---------------------------------------------------------------------------
# Memory detector
# ---------------------------------------------------------------------------


class TestMemoryCeiling:
    def test_triggers_when_current_exceeds_max_mb(self):
        """
        Given max_mb=200 and current RSS=250 MB,
        When check_rss runs,
        Then a memory_ceiling result with severity error is returned.
        """
        history = _stable_history(60, rss_bytes=250 * _MB)
        cfg = RssAnomalyConfig(max_mb=200.0, spike_ratio=None, drop_ratio=None)
        results = check_rss(history, cfg)
        ceiling_results = [r for r in results if r["anomaly_type"] == "rss_ceiling"]
        assert len(ceiling_results) == 1
        assert ceiling_results[0]["severity"] == "error"

    def test_no_trigger_when_below_max(self):
        """
        Given max_mb=500 and current RSS=100 MB,
        When check_rss runs,
        Then no ceiling result.
        """
        history = _stable_history(60, rss_bytes=100 * _MB)
        cfg = RssAnomalyConfig(max_mb=500.0, spike_ratio=None, drop_ratio=None)
        results = check_rss(history, cfg)
        assert all(r["anomaly_type"] != "rss_ceiling" for r in results)


class TestMemorySpike:
    def test_triggers_on_ratio_and_delta(self):
        """
        Given baseline=100 MB and current=200 MB (2x, +100 MB),
        When check_rss runs with spike_ratio=1.5, min_spike_mb=50,
        Then a memory_spike result is returned.
        """
        snaps = [_snap(rss_bytes=100 * _MB) for _ in range(55)]
        snaps += [_snap(rss_bytes=200 * _MB) for _ in range(5)]
        history = _history(*snaps)
        cfg = RssAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_mb=None, spike_ratio=1.5, min_spike_mb=50.0, drop_ratio=None,
        )
        results = check_rss(history, cfg)
        spike_results = [r for r in results if r["anomaly_type"] == "rss_spike"]
        assert len(spike_results) == 1
        assert spike_results[0]["severity"] == "warning"

    def test_no_trigger_when_ratio_not_met(self):
        """
        Given baseline=100 MB and current=120 MB (1.2x < 1.5x),
        When check_rss runs,
        Then no spike result.
        """
        snaps = [_snap(rss_bytes=100 * _MB) for _ in range(55)]
        snaps += [_snap(rss_bytes=120 * _MB) for _ in range(5)]
        history = _history(*snaps)
        cfg = RssAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_mb=None, spike_ratio=1.5, min_spike_mb=50.0, drop_ratio=None,
        )
        results = check_rss(history, cfg)
        assert all(r["anomaly_type"] != "rss_spike" for r in results)


class TestMemoryDrop:
    def test_triggers_on_drop(self):
        """
        Given baseline=400 MB and current=100 MB (0.25x, drop 300 MB),
        When check_rss runs with drop_ratio=0.5, min_drop_mb=100,
        Then a memory_drop result is returned.
        """
        snaps = [_snap(rss_bytes=400 * _MB) for _ in range(55)]
        snaps += [_snap(rss_bytes=100 * _MB) for _ in range(5)]
        history = _history(*snaps)
        cfg = RssAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_mb=None, spike_ratio=None,
            drop_ratio=0.5, min_drop_mb=100.0,
        )
        results = check_rss(history, cfg)
        drop_results = [r for r in results if r["anomaly_type"] == "rss_drop"]
        assert len(drop_results) == 1
        assert drop_results[0]["severity"] == "warning"


class TestMemoryDisabled:
    def test_all_modes_none_returns_empty(self):
        """
        Given all modes disabled,
        When check_rss runs,
        Then empty list is returned.
        """
        history = _stable_history(60, rss_bytes=999 * _MB)
        cfg = RssAnomalyConfig(
            max_mb=None, spike_ratio=None, min_spike_mb=None,
            drop_ratio=None, min_drop_mb=None,
        )
        results = check_rss(history, cfg)
        assert results == []


# ---------------------------------------------------------------------------
# CPU detector
# ---------------------------------------------------------------------------


class TestCpuCeiling:
    def test_triggers_when_exceeds_max_percent(self):
        """
        Given max_percent=80 and current CPU=95%,
        When check_cpu runs,
        Then a cpu_ceiling result with severity error.
        """
        history = _stable_history(60, cpu_percent=95.0)
        cfg = CpuAnomalyConfig(max_percent=80.0, spike_ratio=None, drop_ratio=None)
        results = check_cpu(history, cfg)
        ceiling = [r for r in results if r["anomaly_type"] == "cpu_ceiling"]
        assert len(ceiling) == 1
        assert ceiling[0]["severity"] == "error"


class TestCpuSpike:
    def test_triggers_on_sustained_high_cpu(self):
        """
        Given baseline=20% and current short window=60%,
        When check_cpu runs with spike_ratio=2.5, min_spike_delta=30,
        Then a cpu_spike result.
        """
        snaps = [_snap(cpu_percent=20.0) for _ in range(55)]
        snaps += [_snap(cpu_percent=60.0) for _ in range(5)]
        history = _history(*snaps)
        cfg = CpuAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_percent=None, spike_ratio=2.5, min_spike_delta=30.0,
            drop_ratio=None,
        )
        results = check_cpu(history, cfg)
        spike = [r for r in results if r["anomaly_type"] == "cpu_spike"]
        assert len(spike) == 1


class TestCpuDrop:
    def test_triggers_on_cpu_starvation(self):
        """
        Given baseline=50% and current=5% (0.1x),
        When check_cpu runs with drop_ratio=0.2, min_drop_delta=25,
        Then a cpu_drop result.
        """
        snaps = [_snap(cpu_percent=50.0) for _ in range(55)]
        snaps += [_snap(cpu_percent=5.0) for _ in range(5)]
        history = _history(*snaps)
        cfg = CpuAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_percent=None, spike_ratio=None,
            drop_ratio=0.2, min_drop_delta=25.0,
        )
        results = check_cpu(history, cfg)
        drop = [r for r in results if r["anomaly_type"] == "cpu_drop"]
        assert len(drop) == 1


# ---------------------------------------------------------------------------
# FDs detector
# ---------------------------------------------------------------------------


class TestFdsCeiling:
    def test_triggers_when_exceeds_max_fds(self):
        """
        Given max_fds=100 and current fds=120,
        When check_fds runs,
        Then a fds_ceiling result with severity error.
        """
        history = _stable_history(60, fds=120)
        cfg = FdAnomalyConfig(max_fds=100, spike_ratio=None, drop_ratio=None)
        results = check_fds(history, cfg)
        ceiling = [r for r in results if r["anomaly_type"] == "fds_ceiling"]
        assert len(ceiling) == 1
        assert ceiling[0]["severity"] == "error"


class TestFdsSpike:
    def test_triggers_on_fd_leak(self):
        """
        Given baseline=20 fds and current=80 fds,
        When check_fds runs,
        Then a fds_spike result with severity error (FD leaks always error).
        """
        snaps = [_snap(fds=20) for _ in range(55)]
        snaps += [_snap(fds=80) for _ in range(5)]
        history = _history(*snaps)
        cfg = FdAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_fds=None, spike_ratio=1.5, min_spike_delta=50,
            drop_ratio=None,
        )
        results = check_fds(history, cfg)
        spike = [r for r in results if r["anomaly_type"] == "fds_spike"]
        assert len(spike) == 1
        assert spike[0]["severity"] == "error"

    def test_fds_none_returns_empty(self):
        """
        Given samples with fds=None (V8 degradation),
        When check_fds runs,
        Then empty list (insufficient data).
        """
        history = _stable_history(60, fds=None)
        cfg = FdAnomalyConfig()
        results = check_fds(history, cfg)
        assert results == []


class TestFdsDrop:
    def test_triggers_on_pool_collapse(self):
        """
        Given baseline=200 fds and current=50 fds,
        When check_fds runs with drop_ratio=0.5, min_drop_delta=50,
        Then a fds_drop result.
        """
        snaps = [_snap(fds=200) for _ in range(55)]
        snaps += [_snap(fds=50) for _ in range(5)]
        history = _history(*snaps)
        cfg = FdAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_fds=None, spike_ratio=None,
            drop_ratio=0.5, min_drop_delta=50,
        )
        results = check_fds(history, cfg)
        drop = [r for r in results if r["anomaly_type"] == "fds_drop"]
        assert len(drop) == 1


# ---------------------------------------------------------------------------
# Threads detector
# ---------------------------------------------------------------------------


class TestThreadsCeiling:
    def test_triggers_when_exceeds_max_threads(self):
        """
        Given max_threads=50 and current=60,
        When check_threads runs,
        Then a threads_ceiling result with severity error.
        """
        history = _stable_history(60, threads=60)
        cfg = ThreadAnomalyConfig(max_threads=50, spike_ratio=None, drop_ratio=None)
        results = check_threads(history, cfg)
        ceiling = [r for r in results if r["anomaly_type"] == "threads_ceiling"]
        assert len(ceiling) == 1
        assert ceiling[0]["severity"] == "error"


class TestThreadsSpike:
    def test_triggers_on_thread_growth(self):
        """
        Given baseline=4 and current=20,
        When check_threads runs,
        Then a threads_spike result.
        """
        snaps = [_snap(threads=4) for _ in range(55)]
        snaps += [_snap(threads=20) for _ in range(5)]
        history = _history(*snaps)
        cfg = ThreadAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_threads=None, spike_ratio=1.5, min_spike_delta=10,
            drop_ratio=None,
        )
        results = check_threads(history, cfg)
        spike = [r for r in results if r["anomaly_type"] == "threads_spike"]
        assert len(spike) == 1


class TestThreadsDrop:
    def test_triggers_on_worker_collapse(self):
        """
        Given baseline=40 and current=10,
        When check_threads runs with drop_ratio=0.5, min_drop_delta=5,
        Then a threads_drop result.
        """
        snaps = [_snap(threads=40) for _ in range(55)]
        snaps += [_snap(threads=10) for _ in range(5)]
        history = _history(*snaps)
        cfg = ThreadAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_threads=None, spike_ratio=None,
            drop_ratio=0.5, min_drop_delta=5,
        )
        results = check_threads(history, cfg)
        drop = [r for r in results if r["anomaly_type"] == "threads_drop"]
        assert len(drop) == 1


# ---------------------------------------------------------------------------
# Shared invariants
# ---------------------------------------------------------------------------


class TestInsufficientHistory:
    def test_all_detectors_return_empty_on_too_few_samples(self):
        """
        Given fewer than 3 samples,
        When any detector runs,
        Then empty list is returned.
        """
        history = _history(_snap(), _snap())
        assert check_rss(history, RssAnomalyConfig()) == []
        assert check_cpu(history, CpuAnomalyConfig()) == []
        assert check_fds(history, FdAnomalyConfig()) == []
        assert check_threads(history, ThreadAnomalyConfig()) == []


class TestMultipleModesFireSimultaneously:
    def test_ceiling_and_spike_both_fire(self):
        """
        Given memory at 500 MB (exceeds ceiling 200 MB AND spikes vs baseline 100 MB),
        When check_rss runs,
        Then both ceiling and spike results are returned.
        """
        snaps = [_snap(rss_bytes=100 * _MB) for _ in range(55)]
        snaps += [_snap(rss_bytes=500 * _MB) for _ in range(5)]
        history = _history(*snaps)
        cfg = RssAnomalyConfig(
            duration="25s", baseline_duration="5m",
            max_mb=200.0, spike_ratio=1.5, min_spike_mb=50.0,
            drop_ratio=None,
        )
        results = check_rss(history, cfg)
        types = {r["anomaly_type"] for r in results}
        assert "rss_ceiling" in types
        assert "rss_spike" in types


class TestResultShape:
    def test_result_has_required_keys(self):
        """
        Given a triggering condition,
        When any detector returns results,
        Then each has anomaly_type, current, baseline, severity, window, details.
        """
        history = _stable_history(60, rss_bytes=500 * _MB)
        cfg = RssAnomalyConfig(max_mb=200.0, spike_ratio=None, drop_ratio=None)
        results = check_rss(history, cfg)
        assert len(results) > 0
        required = {"anomaly_type", "current", "baseline", "severity", "window", "details"}
        for r in results:
            assert required.issubset(r.keys()), f"Missing keys in {r}"
