"""psutil-backed vitals sampler adapter.

psutil is a sidecar-only optional dep. Imported at module level (with try/except
fallback to None) so unittest.mock.patch can replace the module attribute in tests.
"""
import logging

from snitchbot.shared.constants import FDS_SAMPLE_INTERVAL_SEC, VITALS_SAMPLE_SEC
from snitchbot.shared.domain import ClientState, VitalsSnapshot

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger("snitchbot.sidecar.psutil_vitals_sampler")

__all__ = ["PsutilVitalsSampler"]

class PsutilVitalsSampler:
    """Samples process vitals via psutil.

    Uses the module-level ``psutil`` attribute so
    ``unittest.mock.patch('...psutil_vitals_sampler.psutil')`` works in tests.

    Invariants:
    - V1: non-FD metrics every VITALS_SAMPLE_SEC (5s)
    - V2: history deque maxlen=60
    - V3: Process object cached per PID
    - V4: create_time guard for PID reuse
    - V5: error on one client doesn't break others
    - V6: NoSuchProcess -> mark dead
    - V7: AccessDenied (whole) -> mark unavailable
    - V8: AccessDenied (num_fds only) -> fds=None
    - V9: FDs every FDS_SAMPLE_INTERVAL_SEC (15s)
    - V10: sleep_remaining anti-drift
    """

    def sample_one_client(self, client: ClientState, *, now: float) -> VitalsSnapshot:
        """Sample one client's vitals and return a VitalsSnapshot.

        Raises:
            psutil.NoSuchProcess: if the PID is gone or PID was reused (V4, V6).
            psutil.AccessDenied: if whole-process access is denied (V7).
            Any other exception propagates to caller.
        """
        # V3: lazy-init and cache Process object
        if client.psutil_process is None:
            proc = psutil.Process(client.pid)
            client.psutil_process = proc
            client.psutil_create_time = proc.create_time()
        else:
            proc = client.psutil_process
            # V4: PID reuse guard
            if proc.create_time() != client.psutil_create_time:
                raise psutil.NoSuchProcess(pid=client.pid)

        # V1: always sample non-FD metrics
        rss = proc.memory_info().rss
        cpu = proc.cpu_percent(interval=None)
        threads = proc.num_threads()

        # V9: FDs sampled at longer interval
        if now - client.fds_last_sampled_at >= FDS_SAMPLE_INTERVAL_SEC:
            try:
                fds: int | None = proc.num_fds()
                client.fds_last_sampled_at = now
            except psutil.AccessDenied:
                # V8: per-metric degradation — FDs unavailable, rest OK
                fds = None
                client.fds_last_sampled_at = now  # don't retry until next interval
        else:
            # Keep previous FD value if not due for resample
            fds = client.latest_vitals.fds if client.latest_vitals is not None else None

        # V11: recursively sample child processes
        rss_child_sum = 0
        cpu_child_sum = 0.0
        children_count = 0
        try:
            for child in proc.children(recursive=True):
                try:
                    rss_child_sum += child.memory_info().rss
                    cpu_child_sum += child.cpu_percent(interval=None)
                    children_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Child vanished or inaccessible — skip silently
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Parent-level error during child enumeration — degrade gracefully
            pass

        snapshot = VitalsSnapshot(
            sampled_at=now,
            rss_bytes=rss,
            cpu_percent=cpu,
            threads=threads,
            fds=fds,
            total_rss_bytes=rss + rss_child_sum,
            total_cpu_percent=cpu + cpu_child_sum,
            children_count=children_count,
        )

        # V2: append to history
        client.vitals_history.append(snapshot)
        client.latest_vitals = snapshot

        return snapshot

    def sample_into_state(self, client: ClientState, *, now: float) -> None:
        """Sample one client, updating its state in-place.

        Handles V6 (NoSuchProcess -> dead) and V7 (AccessDenied -> unavailable).
        Other exceptions are silently dropped (V5).
        """
        try:
            self.sample_one_client(client, now=now)
            client.vitals_status = "ok"
        except psutil.NoSuchProcess:
            # V6: PID gone or reused — mark dead
            client.vitals_status = "dead"
        except psutil.AccessDenied:
            # V7: whole-process access denied
            client.vitals_status = "unavailable"
        except Exception:
            # V5: any other error — don't propagate
            logger.debug("vitals: sampling error for client", exc_info=True)

    def _update_status_by_age(self, client: ClientState, *, now: float) -> None:
        """Downgrade vitals_status based on age of last successful sample (§3.6).

        - Last sample < 15s: stays "ok"
        - Last sample 15-60s: "stale"
        - Last sample > 60s: "dead" (if PID probe fails) or "stale" (still alive)

        Never overrides terminal "unavailable" or an already-"dead" state set
        by sample_one_client (V6/V7).
        """
        if client.vitals_status in ("dead", "unavailable"):
            return
        if client.latest_vitals is None:
            return  # never sampled yet — leave at default
        age = now - client.latest_vitals.sampled_at
        if age < 15.0:
            client.vitals_status = "ok"
        elif age < 60.0:
            client.vitals_status = "stale"
        else:
            # 60+ sec without vitals — probe PID to distinguish stale vs dead
            try:
                if psutil.Process(client.pid).is_running():
                    client.vitals_status = "stale"
                else:
                    client.vitals_status = "dead"
            except Exception:
                client.vitals_status = "dead"

    def run_sampling_tick(
        self, clients: dict[int, ClientState], *, now: float
    ) -> None:
        """Run one sampling tick over all clients.

        Iterates over a snapshot of client values so concurrent modification
        of the dict does not affect the iteration (V5, spec §3.4).
        After sampling, applies age-based status downgrade (§3.6).
        """
        for client in list(clients.values()):
            self.sample_into_state(client, now=now)
            self._update_status_by_age(client, now=now)

    @staticmethod
    def compute_sleep_remaining(elapsed: float) -> float:
        """Return seconds to sleep to maintain the VITALS_SAMPLE_SEC cadence.

        V10: sleep(max(0, VITALS_SAMPLE_SEC - elapsed)) anti-drift pattern.
        """
        return max(0.0, VITALS_SAMPLE_SEC - elapsed)
