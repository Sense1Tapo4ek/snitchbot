"""Flow tests for TickIdleWatcherUseCase.

Validates §7.6 idle watcher behavior.
"""
import os
import time
from unittest.mock import patch

from snitchbot.sidecar.session.app.use_cases.tick_idle_watcher_uc import TickIdleWatcherUseCase
from snitchbot.sidecar.session.domain.session_agg import SidecarSession

IDLE_TIMEOUT = 30.0


class FakeClient:
    """Minimal client stub with goodbye protocol fields."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.service = "test-svc"
        self.role = "standalone"
        self.shutdown_received = False
        self.dead_detected_at: float | None = None


class FakeClientRegistry:
    """Minimal stub satisfying IClientRegistry for flow tests.

    Avoids importing the concrete ClientRegistry from the ingest context —
    keeps the session flow tests decoupled per S-DDD rules.
    """

    def __init__(self, *pids: int) -> None:
        self._clients: dict[int, FakeClient] = {
            pid: FakeClient(pid) for pid in pids
        }

    def all_pids(self) -> list[int]:
        return list(self._clients.keys())

    def get_by_pid(self, pid: int) -> FakeClient | None:
        return self._clients.get(pid)

    def is_empty(self) -> bool:
        return not self._clients

    def remove(self, pid: int) -> None:
        self._clients.pop(pid, None)

    def contains(self, pid: int) -> bool:
        return pid in self._clients


def _make_session(*, first_hello: bool = True, last_activity_offset: float = 0.0) -> SidecarSession:
    """Create a SidecarSession with controllable state."""
    session = SidecarSession(started_at=time.monotonic())
    if first_hello:
        session.first_hello_received = True
        session.last_activity_at = time.monotonic() - last_activity_offset
    return session


def _make_registry(*pids: int) -> FakeClientRegistry:
    return FakeClientRegistry(*pids)


def _make_uc(
    session: SidecarSession,
    registry: FakeClientRegistry,
    idle_timeout: float = IDLE_TIMEOUT,
    on_killed=None,
) -> TickIdleWatcherUseCase:
    return TickIdleWatcherUseCase(
        _session=session,
        _registry=registry,
        _idle_timeout_sec=idle_timeout,
        _on_client_killed=on_killed,
    )


class TestNoExitBeforeFirstHello:
    def test_no_exit_before_first_hello(self):
        """
        Given sidecar has not yet received first hello (§7.6),
        When calling TickIdleWatcherUseCase,
        Then returns False (no exit).
        """
        # Arrange
        session = SidecarSession(started_at=time.monotonic())
        session.first_hello_received = False
        session.last_activity_at = 0.0  # effectively infinite idle
        registry = _make_registry()
        uc = _make_uc(session, registry, idle_timeout=0.0)  # timeout=0 to force exit if logic wrong

        # Act
        result = uc()

        # Assert
        assert result is False


class TestIdleExit:
    def test_exit_after_idle_timeout_with_empty_registry(self):
        """
        Given first hello was received, registry is empty, idle > timeout,
        When calling TickIdleWatcherUseCase,
        Then returns True (should exit).
        """
        # Arrange
        session = _make_session(first_hello=True, last_activity_offset=IDLE_TIMEOUT + 1.0)
        registry = _make_registry()  # empty
        uc = _make_uc(session, registry)

        # Act
        result = uc()

        # Assert
        assert result is True

    def test_no_exit_while_clients_alive(self):
        """
        Given first hello received and registry has a live client,
        When calling TickIdleWatcherUseCase,
        Then returns False regardless of idle time.
        """
        # Arrange
        session = _make_session(first_hello=True, last_activity_offset=IDLE_TIMEOUT + 100.0)
        registry = _make_registry(os.getpid())  # own pid is always alive
        uc = _make_uc(session, registry)

        # Act
        result = uc()

        # Assert
        assert result is False

    def test_activity_resets_idle_timer(self):
        """
        Given first hello received, empty registry but last activity just happened,
        When calling TickIdleWatcherUseCase,
        Then returns False (idle timer not yet expired).
        """
        # Arrange — last_activity_at = just now
        session = _make_session(first_hello=True, last_activity_offset=0.0)
        registry = _make_registry()  # empty but fresh activity
        uc = _make_uc(session, registry, idle_timeout=IDLE_TIMEOUT)

        # Act
        result = uc()

        # Assert
        assert result is False


class TestDeadClientRemoval:
    def test_dead_client_removed_after_grace_period(self):
        """
        Given a client pid that is dead (os.kill raises ProcessLookupError),
        When calling TickIdleWatcherUseCase twice (grace period expires),
        Then client is removed from registry on the second call.
        """
        # Arrange
        dead_pid = 999999
        session = _make_session(first_hello=True, last_activity_offset=IDLE_TIMEOUT + 1.0)
        registry = _make_registry(dead_pid)
        killed_pids: list[int] = []
        uc = _make_uc(session, registry, on_killed=lambda p, s, r: killed_pids.append(p))

        def fake_kill(pid: int, sig: int) -> None:
            raise ProcessLookupError(f"No process {pid}")

        _patch = "snitchbot.sidecar.session.app.use_cases.tick_idle_watcher_uc.os.kill"

        # Act — first call: detects death, starts grace period
        with patch(_patch, fake_kill):
            uc()
        assert registry.contains(dead_pid)  # still there (grace period)

        # Fast-forward grace period
        client = registry.get_by_pid(dead_pid)
        client.dead_detected_at -= 15.0  # pretend 15s have passed (> 10s grace)

        # Act — second call: grace expired, emits killed, removes
        with patch(_patch, fake_kill):
            result = uc()

        # Assert
        assert not registry.contains(dead_pid)
        assert killed_pids == [dead_pid]
        assert result is True  # registry empty + idle expired

    def test_dead_client_with_shutdown_received_removed_immediately(self):
        """
        Given a client that sent a proper shutdown event (shutdown_received=True),
        When it dies and TickIdleWatcherUseCase runs,
        Then it is removed immediately without killed event.
        """
        # Arrange
        dead_pid = 999999
        session = _make_session(first_hello=True, last_activity_offset=IDLE_TIMEOUT + 1.0)
        registry = _make_registry(dead_pid)
        registry.get_by_pid(dead_pid).shutdown_received = True
        killed_pids: list[int] = []
        uc = _make_uc(session, registry, on_killed=lambda p, s, r: killed_pids.append(p))

        def fake_kill(pid: int, sig: int) -> None:
            raise ProcessLookupError(f"No process {pid}")

        _patch = "snitchbot.sidecar.session.app.use_cases.tick_idle_watcher_uc.os.kill"

        # Act
        with patch(_patch, fake_kill):
            result = uc()

        # Assert — removed immediately, no killed event
        assert not registry.contains(dead_pid)
        assert killed_pids == []
        assert result is True


