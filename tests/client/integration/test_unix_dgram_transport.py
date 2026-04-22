"""Integration tests for UnixDgramTransport.

Uses real AF_UNIX DGRAM sockets via tmp_path fixtures.
No mocks — real OS socket operations only (except EAGAIN simulation).
"""
import errno
import socket
import unittest.mock as mock

import pytest

from snitchbot.client.errors import TransportError
from snitchbot.client.ports.driven.transport.unix_dgram_transport import UnixDgramTransport
from snitchbot.shared.generics.errors import PortError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server_socket(tmp_path):
    """Bind a real DGRAM listener at tmp_path / 'test.sock'."""
    path = tmp_path / "test.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    yield sock, path
    sock.close()


@pytest.fixture
def transport():
    """Fresh UnixDgramTransport, closed after each test."""
    t = UnixDgramTransport()
    yield t
    t.close()


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_transport_error_is_port_error():
    """TransportError must be a subclass of PortError."""
    assert issubclass(TransportError, PortError)


# ---------------------------------------------------------------------------
# is_connected initial state
# ---------------------------------------------------------------------------


def test_is_connected_false_initially(transport):
    """
    Given a freshly constructed transport,
    When checking is_connected,
    Then it must be False.
    """
    assert transport.is_connected is False


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


def test_connect_to_existing_socket_succeeds(transport, server_socket):
    """
    Given a bound DGRAM server socket at a known path,
    When connecting the transport to that path,
    Then is_connected becomes True and no exception is raised.
    """
    _, path = server_socket
    transport.connect(path)
    assert transport.is_connected is True


def test_connect_to_missing_socket_raises(transport, tmp_path):
    """
    Given a path that does not exist on the filesystem,
    When connecting the transport to that path,
    Then TransportError is raised.
    """
    missing = tmp_path / "no_such.sock"
    with pytest.raises(TransportError):
        transport.connect(missing)


def test_connect_to_stale_socket_raises(transport, tmp_path):
    """
    Given a regular file at a socket path (stale / unbound socket file),
    When connecting the transport to that path,
    Then TransportError is raised because connecting to a non-socket path fails.

    Note: on Linux, connect() to a regular file raises ECONNREFUSED or ENOTSOCK.
    We touch() a plain file to simulate a stale socket inode with no listener.
    """
    stale = tmp_path / "stale.sock"
    stale.touch()  # plain file, not a bound DGRAM socket
    with pytest.raises(TransportError):
        transport.connect(stale)


# ---------------------------------------------------------------------------
# is_connected after connect / close
# ---------------------------------------------------------------------------


def test_is_connected_true_after_connect(transport, server_socket):
    """
    Given a bound server socket,
    When the transport connects,
    Then is_connected is True.
    """
    _, path = server_socket
    transport.connect(path)
    assert transport.is_connected is True


def test_is_connected_false_after_close(transport, server_socket):
    """
    Given a connected transport,
    When close() is called,
    Then is_connected becomes False.
    """
    _, path = server_socket
    transport.connect(path)
    transport.close()
    assert transport.is_connected is False


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------


def test_send_succeeds(transport, server_socket):
    """
    Given a connected transport and a listening server socket,
    When sending bytes,
    Then the server socket receives exactly those bytes.
    """
    server_sock, path = server_socket
    server_sock.setblocking(False)

    payload = b"hello sidecar"
    transport.connect(path)
    transport.send(payload)

    received = server_sock.recv(4096)
    assert received == payload


def test_send_after_close_raises(transport, server_socket):
    """
    Given a transport that was connected and then closed,
    When send() is called,
    Then TransportError('Not connected') is raised.
    """
    _, path = server_socket
    transport.connect(path)
    transport.close()

    with pytest.raises(TransportError, match="Not connected"):
        transport.send(b"data")


# ---------------------------------------------------------------------------
# close() idempotence
# ---------------------------------------------------------------------------


def test_close_idempotent(transport, server_socket):
    """
    Given a connected transport,
    When close() is called twice,
    Then no exception is raised on the second call.
    """
    _, path = server_socket
    transport.connect(path)
    transport.close()
    transport.close()  # must not raise


def test_close_on_unconnected_transport_is_safe(transport):
    """
    Given a transport that was never connected,
    When close() is called,
    Then no exception is raised.
    """
    transport.close()


# ---------------------------------------------------------------------------
# EAGAIN / buffer-full path (simulated via mock)
# ---------------------------------------------------------------------------


def test_send_nonblocking_eagain_raises_transport_error(transport, server_socket):
    """
    Given a connected transport whose _send raises BlockingIOError (EAGAIN),
    When send() is called,
    Then TransportError('Buffer full') is raised.

    EAGAIN is hard to trigger reliably without filling kernel buffers,
    so we patch the internal _send() helper to simulate it.
    """
    _, path = server_socket
    transport.connect(path)

    with mock.patch.object(
        transport,
        "_send",
        side_effect=BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable"),
    ):
        with pytest.raises(TransportError, match="EAGAIN"):
            transport.send(b"x")


def test_send_enobufs_raises_transport_error(transport, server_socket):
    """
    Given a connected transport whose _send raises OSError with ENOBUFS,
    When send() is called,
    Then TransportError('ENOBUFS') is raised.
    """
    _, path = server_socket
    transport.connect(path)

    with mock.patch.object(
        transport,
        "_send",
        side_effect=OSError(errno.ENOBUFS, "No buffer space available"),
    ):
        with pytest.raises(TransportError, match="ENOBUFS"):
            transport.send(b"x")


# ---------------------------------------------------------------------------
# recv()
# ---------------------------------------------------------------------------


class TestRecv:
    def test_recv_returns_data_within_timeout(self, server_socket):
        """
        Given a connected transport and server that sends data,
        When recv is called with sufficient timeout,
        Then the sent data is returned.
        """
        sock, path = server_socket
        transport = UnixDgramTransport()
        transport.connect(path)

        # Client sends first so server knows the client address
        transport.send(b"ping")
        data, client_addr = sock.recvfrom(65536)
        sock.sendto(b"pong", client_addr)

        result = transport.recv(timeout_ms=1000)
        assert result == b"pong"
        transport.close()

    def test_recv_returns_none_on_timeout(self, server_socket):
        """
        Given a connected transport and no data sent,
        When recv is called with short timeout,
        Then None is returned (no hang).
        """
        sock, path = server_socket
        transport = UnixDgramTransport()
        transport.connect(path)
        result = transport.recv(timeout_ms=50)
        assert result is None
        transport.close()

    def test_recv_raises_when_not_connected(self):
        """
        Given a transport not yet connected,
        When recv is called,
        Then TransportError is raised.
        """
        transport = UnixDgramTransport()
        with pytest.raises(TransportError):
            transport.recv(timeout_ms=100)
