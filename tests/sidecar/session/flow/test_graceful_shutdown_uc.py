"""Flow tests for GracefulShutdownUseCase.

Invariants validated: I4 (exit paths), I5 (socket unlinked on exit).
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.session.app.use_cases.graceful_shutdown_uc import GracefulShutdownUseCase
from snitchbot.sidecar.session.domain.session_agg import SidecarSession


def _make_session() -> SidecarSession:
    return SidecarSession(started_at=time.monotonic())


def _make_uc(session: SidecarSession, drain_timeout: float = 5.0) -> GracefulShutdownUseCase:
    return GracefulShutdownUseCase(
        _session=session,
        _drain_timeout_sec=drain_timeout,
    )


@pytest.mark.asyncio
class TestShutdownMarksSession:
    async def test_shutdown_marks_session_requested(self):
        """
        Given a running session,
        When calling GracefulShutdownUseCase,
        Then session.shutdown_requested is True after call.
        """
        # Arrange
        session = _make_session()
        uc = _make_uc(session)
        close_socket = MagicMock()
        unlink_socket = MagicMock()
        drain_queue = AsyncMock()

        # Act
        await uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

        # Assert
        assert session.shutdown_requested is True


@pytest.mark.asyncio
class TestShutdownDrainsQueue:
    async def test_shutdown_drains_queue_up_to_5s(self):
        """
        Given a drain_queue coroutine,
        When calling GracefulShutdownUseCase,
        Then drain_queue is awaited (with up to drain_timeout_sec).
        """
        # Arrange
        session = _make_session()
        uc = _make_uc(session, drain_timeout=5.0)
        close_socket = MagicMock()
        unlink_socket = MagicMock()
        drain_queue = AsyncMock()

        # Act
        await uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

        # Assert
        drain_queue.assert_awaited_once()


@pytest.mark.asyncio
class TestShutdownSocket:
    async def test_shutdown_closes_socket(self):
        """
        Given a close_socket callable (invariant I5 — socket released),
        When calling GracefulShutdownUseCase,
        Then close_socket() is called exactly once.
        """
        # Arrange
        session = _make_session()
        uc = _make_uc(session)
        close_socket = MagicMock()
        unlink_socket = MagicMock()
        drain_queue = AsyncMock()

        # Act
        await uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

        # Assert
        close_socket.assert_called_once()

    async def test_shutdown_unlinks_socket_file(self):
        """
        Given an unlink_socket callable (invariant I4/I5 — socket file removed),
        When calling GracefulShutdownUseCase,
        Then unlink_socket() is called exactly once.
        """
        # Arrange
        session = _make_session()
        uc = _make_uc(session)
        close_socket = MagicMock()
        unlink_socket = MagicMock()
        drain_queue = AsyncMock()

        # Act
        await uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

        # Assert
        unlink_socket.assert_called_once()


@pytest.mark.asyncio
class TestShutdownOrder:
    async def test_shutdown_order_drain_then_close_then_unlink(self):
        """
        Given all shutdown callables,
        When calling GracefulShutdownUseCase,
        Then order is: drain_queue -> close_socket -> unlink_socket (per §7.7).
        """
        # Arrange
        session = _make_session()
        uc = _make_uc(session)
        call_order: list[str] = []

        async def drain_queue() -> None:
            call_order.append("drain")

        def close_socket() -> None:
            call_order.append("close")

        def unlink_socket() -> None:
            call_order.append("unlink")

        # Act
        await uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

        # Assert
        assert call_order == ["drain", "close", "unlink"]
