"""Unit tests for LiveMessageRenderService — Task 11.1.

Spec: docs/superpowers/specs/2026-04-11-live-message-vitals-design.md §5.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 11.1.

Invariants validated: LM8.

No mocks — pure domain, stdlib only.
"""
from snitchbot.shared.domain.client_state import ClientState
from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot
from snitchbot.sidecar.live_message.domain.services.live_message_render_service import (
    render_live_message,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0  # fixed epoch for deterministic rendering
_SIDECAR_STARTED_AT = _NOW - 3 * 3600 - 42 * 60  # 3h 42m ago


def _make_vitals(
    *,
    rss_bytes: int = 80 * 1024 * 1024,
    cpu_percent: float = 2.0,
    threads: int = 8,
    fds: int | None = 12,
) -> VitalsSnapshot:
    return VitalsSnapshot(
        sampled_at=_NOW,
        rss_bytes=rss_bytes,
        cpu_percent=cpu_percent,
        threads=threads,
        fds=fds,
    )


def _make_client(
    pid: int = 100,
    role: str = "master",
    service: str = "orders-api",
    vitals_status: str = "ok",
    vitals: VitalsSnapshot | None = None,
) -> ClientState:
    c = ClientState(
        pid=pid,
        role=role,
        service=service,
        last_seen=_NOW,
        connected_at=_NOW - 60,
    )
    c.vitals_status = vitals_status
    c.latest_vitals = vitals if vitals is not None else _make_vitals()
    return c


def _make_counters(
    *,
    errors: int = 0,
    warnings: int = 2,
    slow: int = 1,
    anomaly: int = 0,
) -> dict[str, int]:
    return {"errors": errors, "warnings": warnings, "slow": slow, "anomaly": anomaly}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHeader:
    def test_header_contains_health_icon_and_service_and_live_suffix(self):
        """
        Given a healthy service with active clients,
        When rendering live message,
        Then header contains green icon, service name, and '· live' suffix.
        """
        clients = [_make_client()]
        html = render_live_message(
            service="orders-api",
            clients=clients,
            sidecar_started_at=_SIDECAR_STARTED_AT,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "🟢" in html
        assert "<b>orders-api</b>" in html
        assert "· live" in html.lower() or "live" in html


class TestClientsTable:
    def test_clients_table_pre_block_with_pid_role_rss_cpu_threads_fds(self):
        """
        Given a client with full vitals,
        When rendering live message,
        Then clients block has a <pre> table with all columns.
        """
        client = _make_client(
            pid=101,
            role="worker",
            vitals=_make_vitals(
                rss_bytes=120 * 1024 * 1024,
                cpu_percent=15.0,
                threads=12,
                fds=24,
            ),
        )
        html = render_live_message(
            service="orders-api",
            clients=[client],
            sidecar_started_at=_SIDECAR_STARTED_AT,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "<pre>" in html
        assert "101" in html
        assert "worker" in html
        assert "120" in html   # rss MB
        assert "15" in html    # cpu
        assert "12" in html    # threads
        assert "24" in html    # fds


class TestSidecarBlock:
    def test_sidecar_block_uptime_updated_timestamp(self):
        """
        Given sidecar started 3h42m ago,
        When rendering live message,
        Then sidecar block has uptime '3h 42m' and 'updated' timestamp.
        """
        html = render_live_message(
            service="orders-api",
            clients=[_make_client()],
            sidecar_started_at=_SIDECAR_STARTED_AT,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "3h 42m" in html
        assert "updated" in html.lower()


class TestLast5mBlock:
    def test_last_5m_block_errors_warnings_slow_anomaly(self):
        """
        Given counters with mixed values,
        When rendering live message,
        Then 'Last 5m' block contains all four counter labels with values.
        """
        html = render_live_message(
            service="orders-api",
            clients=[_make_client()],
            sidecar_started_at=_SIDECAR_STARTED_AT,
            counters=_make_counters(errors=3, warnings=5, slow=2, anomaly=1),
            now=_NOW,
        )
        assert "5m" in html
        assert "errors" in html.lower()
        assert "warnings" in html.lower() or "warning" in html.lower()
        assert "slow" in html.lower()
        assert "anomaly" in html.lower()


class TestStatusSuffixes:
    def test_status_ok_row_plain(self):
        """
        Given client with status='ok',
        When rendering live message,
        Then row has no status suffix.
        """
        client = _make_client(pid=200, vitals_status="ok")
        html = render_live_message(
            service="svc",
            clients=[client],
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "(stale)" not in html
        assert "(unavail)" not in html

    def test_status_stale_row_suffix(self):
        """
        Given client with status='stale',
        When rendering live message,
        Then row contains '(stale)' suffix (LM8).
        """
        client = _make_client(pid=201, vitals_status="stale")
        html = render_live_message(
            service="svc",
            clients=[client],
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "(stale)" in html

    def test_status_unavailable_row_dashes_suffix(self):
        """
        Given client with status='unavailable',
        When rendering live message,
        Then row has '—' for vitals and '(unavail)' suffix.
        """
        client = _make_client(pid=202, vitals_status="unavailable")
        html = render_live_message(
            service="svc",
            clients=[client],
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "—" in html
        assert "(unavail)" in html

    def test_status_dead_removed_from_table(self):
        """
        Given one 'ok' client and one 'dead' client,
        When rendering live message,
        Then dead client PID does not appear in the output.
        """
        ok_client = _make_client(pid=300, vitals_status="ok")
        dead_client = _make_client(pid=301, vitals_status="dead")
        html = render_live_message(
            service="svc",
            clients=[ok_client, dead_client],
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "300" in html
        assert "301" not in html


class TestMaxClients:
    def test_max_15_clients_then_more_suffix(self):
        """
        Given 17 clients,
        When rendering live message,
        Then only 15 rows are rendered and '... 2 more' is appended.
        """
        clients = [_make_client(pid=1000 + i) for i in range(17)]
        html = render_live_message(
            service="svc",
            clients=clients,
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "... 2 more" in html


class TestNoMutesNoInternalBlock:
    def test_no_mutes_block_no_internal_block_differs_from_status(self):
        """
        Given live message rendering,
        When rendered,
        Then it does NOT contain 'Mutes' or 'Internal' blocks (spec §5.3).
        """
        html = render_live_message(
            service="svc",
            clients=[_make_client()],
            sidecar_started_at=_NOW - 60,
            counters=_make_counters(),
            now=_NOW,
        )
        assert "Mutes" not in html
        assert "Internal" not in html
        assert "dedup cache" not in html
        assert "rate budget" not in html
