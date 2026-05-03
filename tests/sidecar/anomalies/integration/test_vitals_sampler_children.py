"""Integration test: PsutilVitalsSampler discovers child processes.

Spawns a real child process, samples the parent via PsutilVitalsSampler,
and asserts that total_rss >= rss and children_count >= 1.
"""
import multiprocessing
import time

import pytest

from snitchbot.shared.domain.client_state import ClientState
from snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler import (
    PsutilVitalsSampler,
)


def _child_worker() -> None:
    """Simple worker that sleeps so it stays alive during sampling."""
    time.sleep(5)


@pytest.mark.skipif(
    not PsutilVitalsSampler,
    reason="psutil not installed",
)
class TestPsutilVitalsSamplerChildren:
    def test_sampler_finds_children(self) -> None:
        """
        Given the current process has one child worker,
        When sample_one_client is called on the current PID,
        Then children_count >= 1 and total_rss >= rss_bytes.
        """
        import os

        child = multiprocessing.Process(target=_child_worker)
        child.start()
        try:
            client = ClientState(
                pid=os.getpid(),
                role="test",
                service="test-svc",
                last_seen=time.time(),
                connected_at=time.time(),
            )
            sampler = PsutilVitalsSampler()
            snapshot = sampler.sample_one_client(client, now=time.time())

            assert snapshot.children_count >= 1, (
                f"Expected at least 1 child, got {snapshot.children_count}"
            )
            assert snapshot.total_rss_bytes >= snapshot.rss_bytes, (
                f"total_rss ({snapshot.total_rss_bytes}) < rss ({snapshot.rss_bytes})"
            )
            assert snapshot.total_cpu_percent >= snapshot.cpu_percent, (
                f"total_cpu ({snapshot.total_cpu_percent}) < cpu ({snapshot.cpu_percent})"
            )
        finally:
            child.terminate()
            child.join(timeout=2)
            if child.is_alive():
                child.kill()
