"""Unit tests for chart_data_service — metric extraction and downsampling.

Pure domain: no mocks needed.
"""
import time
from collections import deque

from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.interactive.domain.services.chart_data_service import (
    downsample,
    extract_metric_series,
)

_MB = 1024 * 1024


def _snap(
    offset: float = 0.0,
    rss_bytes: int = 100 * _MB,
    cpu_percent: float = 10.0,
    threads: int = 4,
    fds: int | None = 20,
    base_time: float = 0.0,
    total_rss_bytes: int | None = None,
    total_cpu_percent: float | None = None,
    children_count: int = 0,
) -> VitalsSnapshot:
    return VitalsSnapshot(
        sampled_at=base_time + offset,
        rss_bytes=rss_bytes,
        cpu_percent=cpu_percent,
        threads=threads,
        fds=fds,
        total_rss_bytes=total_rss_bytes if total_rss_bytes is not None else rss_bytes,
        total_cpu_percent=total_cpu_percent if total_cpu_percent is not None else cpu_percent,
        children_count=children_count,
    )


class TestExtractMetricSeries:
    def test_extracts_cpu_within_window(self):
        """
        Given 10 snapshots over 50s (5s apart),
        When extracting cpu for last 30s,
        Then only the last 6 snapshots are returned.
        """
        now = 100.0
        history = deque()
        for i in range(10):
            history.append(_snap(offset=i * 5, cpu_percent=float(i * 10), base_time=50.0))

        series = extract_metric_series(history, metric="cpu", window_sec=30.0, now=now)
        # t=50..95 (5s apart). cutoff=100-30=70. t>=70: 70,75,80,85,90,95 -> 6 values
        assert len(series) == 6

    def test_extracts_mem_as_mb(self):
        """
        Given snapshots with rss_bytes,
        When extracting mem,
        Then values are in MB.
        """
        history = deque()
        history.append(_snap(rss_bytes=200 * _MB, base_time=90.0))
        series = extract_metric_series(history, metric="mem", window_sec=60.0, now=100.0)
        assert len(series) == 1
        assert series[0] == 200.0

    def test_skips_none_fds(self):
        """
        Given snapshots with fds=None (V8),
        When extracting fds,
        Then None values are skipped.
        """
        history = deque()
        history.append(_snap(fds=None, base_time=90.0))
        history.append(_snap(fds=50, base_time=95.0))
        series = extract_metric_series(history, metric="fds", window_sec=60.0, now=100.0)
        assert series == [50.0]

    def test_empty_history_returns_empty(self):
        """
        Given empty history,
        When extracting any metric,
        Then empty list returned.
        """
        series = extract_metric_series(deque(), metric="cpu", window_sec=60.0, now=100.0)
        assert series == []

    def test_invalid_metric_returns_empty(self):
        """
        Given an invalid metric name,
        When extracting,
        Then empty list returned.
        """
        history = deque([_snap(base_time=90.0)])
        series = extract_metric_series(history, metric="bogus", window_sec=60.0, now=100.0)
        assert series == []


class TestDownsample:
    def test_passthrough_when_under_limit(self):
        """
        Given 30 points and max_points=60,
        When downsample is called,
        Then original series is returned unchanged.
        """
        series = list(range(30))
        result = downsample(series, max_points=60)
        assert result == series

    def test_reduces_to_max_points(self):
        """
        Given 120 points and max_points=60,
        When downsample is called,
        Then result has exactly 60 points.
        """
        series = list(range(120))
        result = downsample(series, max_points=60)
        assert len(result) == 60

    def test_averages_correctly(self):
        """
        Given [1,2,3,4] with max_points=2,
        When downsample is called,
        Then result is [1.5, 3.5] (averages of pairs).
        """
        result = downsample([1.0, 2.0, 3.0, 4.0], max_points=2)
        assert len(result) == 2
        assert result[0] == 1.5
        assert result[1] == 3.5

    def test_empty_series(self):
        """
        Given empty series,
        When downsample is called,
        Then empty list returned.
        """
        assert downsample([], max_points=60) == []
