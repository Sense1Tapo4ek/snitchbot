"""Integration tests for ListeningSocket — TDD RED phase."""
import os
import socket
import stat
from pathlib import Path

import pytest

from snitchbot.sidecar.ingest.ports.driven.listening_socket import ListeningSocket


def test_bind_creates_socket_file(tmp_path):
    """
    Given a path under tmp_path,
    When bind() is called,
    Then the socket file exists on disk.
    """
    sock_path = tmp_path / "snitchbot.sock"
    ls = ListeningSocket(sock_path)
    try:
        ls.bind()
        assert sock_path.exists()
    finally:
        ls.close()
        ls.unlink()


def test_bind_unlinks_stale_file_first(tmp_path):
    """
    Given a stale regular file at the socket path (§8.3),
    When bind() is called,
    Then the stale file is removed and bind succeeds.
    """
    sock_path = tmp_path / "stale.sock"
    sock_path.write_text("stale content")  # simulate stale socket file

    ls = ListeningSocket(sock_path)
    try:
        ls.bind()  # should not raise
        assert sock_path.exists()
    finally:
        ls.close()
        ls.unlink()


def test_bind_chmods_socket_to_0600(tmp_path):
    """
    Given a fresh socket path,
    When bind() is called,
    Then the socket file permissions are 0600 (§6.4).
    """
    sock_path = tmp_path / "snitchbot.sock"
    ls = ListeningSocket(sock_path)
    try:
        ls.bind()
        mode = stat.S_IMODE(os.stat(sock_path).st_mode)
        assert mode == 0o600
    finally:
        ls.close()
        ls.unlink()


def test_bind_creates_parent_dir_0700(tmp_path):
    """
    Given a socket path whose parent does not exist,
    When bind() is called,
    Then the parent directory is created with mode 0700 (§6.4).
    """
    sock_path = tmp_path / "subdir" / "snitchbot.sock"
    ls = ListeningSocket(sock_path)
    try:
        ls.bind()
        parent_mode = stat.S_IMODE(os.stat(sock_path.parent).st_mode)
        assert parent_mode == 0o700
    finally:
        ls.close()
        ls.unlink()


def test_bind_eaddrinuse_exits_0(tmp_path):
    """
    Given another socket already bound to the same path (§7.1),
    When a second ListeningSocket.bind() is called,
    Then SystemExit(0) is raised.
    """
    import unittest.mock as mock

    sock_path = tmp_path / "race.sock"

    # Bind a raw socket to hold the address in the kernel
    winner = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    winner.bind(str(sock_path))
    try:
        ls = ListeningSocket(sock_path)
        # Patch the _path so unlink() is a no-op — simulates the race window
        # where the file still exists (held by winner) after we "unlinked" ours
        fake_path = mock.MagicMock(spec=Path)
        fake_path.__str__ = mock.Mock(return_value=str(sock_path))
        fake_path.parent = sock_path.parent
        fake_path.unlink = mock.Mock()  # no-op — don't remove winner's file
        ls._path = fake_path

        with pytest.raises(SystemExit) as exc_info:
            ls.bind()
        assert exc_info.value.code == 0
    finally:
        winner.close()
        sock_path.unlink(missing_ok=True)


def test_sock_type_is_AF_UNIX_DGRAM(tmp_path):
    """
    Given a bound ListeningSocket,
    When inspecting the underlying socket type,
    Then it is AF_UNIX SOCK_DGRAM.
    """
    sock_path = tmp_path / "snitchbot.sock"
    ls = ListeningSocket(sock_path)
    try:
        ls.bind()
        raw = socket.fromfd(ls.fileno, socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            assert raw.family == socket.AF_UNIX
            assert raw.type & socket.SOCK_DGRAM == socket.SOCK_DGRAM
        finally:
            raw.detach()
    finally:
        ls.close()
        ls.unlink()


def test_recvfrom_receives_data(tmp_path):
    """
    Given a bound server and a client socket,
    When client sends data to server,
    Then recvfrom() returns that data.
    """
    server_path = tmp_path / "server.sock"
    client_path = tmp_path / "client.sock"

    server = ListeningSocket(server_path)
    server.bind()

    client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    client_sock.bind(str(client_path))
    try:
        payload = b"hello sidecar"
        client_sock.sendto(payload, str(server_path))

        data, addr = server.recvfrom()

        assert data == payload
    finally:
        client_sock.close()
        client_path.unlink(missing_ok=True)
        server.close()
        server.unlink()


def test_sendto_replies_to_client(tmp_path):
    """
    Given a bound server and a bound client,
    When server.sendto() is called with client's address,
    Then client socket receives the data.
    """
    server_path = tmp_path / "server.sock"
    client_path = tmp_path / "client.sock"

    server = ListeningSocket(server_path)
    server.bind()

    client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    client_sock.bind(str(client_path))
    try:
        # Send something so server knows the client address
        client_sock.sendto(b"ping", str(server_path))
        _, sender_addr = server.recvfrom()

        # Server replies
        server.sendto(b"pong", sender_addr)

        reply = client_sock.recv(256)
        assert reply == b"pong"
    finally:
        client_sock.close()
        client_path.unlink(missing_ok=True)
        server.close()
        server.unlink()


def test_close_idempotent(tmp_path):
    """
    Given a bound and then closed ListeningSocket,
    When close() is called again,
    Then no exception is raised.
    """
    sock_path = tmp_path / "snitchbot.sock"
    ls = ListeningSocket(sock_path)
    ls.bind()
    ls.close()
    ls.close()  # second close must not raise
    ls.unlink()
