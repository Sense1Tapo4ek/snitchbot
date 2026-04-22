"""Flow tests for RecvLoop (driving adapter).

Task 3.3 — Recv Loop and Routing.

Uses mocked socket, codec, register_uc, registry, and queue.
No real I/O.
"""
import time
from unittest.mock import MagicMock

import pytest

from snitchbot.shared.adapters.driven.codec.msgpack_codec import CodecError
from snitchbot.sidecar.pipeline.domain.central_queue_agg import CentralQueue, QueueItem, QueuePriority
from snitchbot.sidecar.ingest.adapters.driving.recv_loop import RecvLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTION_TO_PRIORITY = {
    "new_alert": QueuePriority.NEW_ALERT,
    "counter_edit": QueuePriority.COUNTER_EDIT,
    "severity_upgrade": QueuePriority.SEVERITY_UPGRADE,
    "lifecycle_bypass": QueuePriority.NEW_ALERT,
}


def _make_enqueue_fn(queue: CentralQueue, dedup_cache=None):
    """Build an enqueue_fn that properly creates QueueItems for CentralQueue.

    Mirrors the composition-root wiring: classify via dedup (if present),
    then enqueue a QueueItem.
    """
    def enqueue_fn(event: dict, fingerprint: str | None) -> tuple[bool, str, dict]:
        action = "new_alert"
        if dedup_cache is not None and fingerprint is not None:
            action = dedup_cache.classify(
                fingerprint=fingerprint,
                severity=event.get("severity"),
                event=event,
                now=time.monotonic(),
            )
        enriched = {**event, "fingerprint": fingerprint, "action": action}
        priority = _ACTION_TO_PRIORITY.get(action, QueuePriority.NEW_ALERT)
        if event.get("severity") == "critical":
            priority = QueuePriority.CRITICAL
        accepted = queue.enqueue(QueueItem(priority=priority, payload=enriched))
        return accepted, action, enriched

    return enqueue_fn


def _make_loop(
    *,
    recvfrom_side_effect=None,
    codec_unpack_return=None,
    codec_unpack_side_effect=None,
    register_uc_return=None,
    registry_get=None,
    queue=None,
    stats=None,
    enqueue_fn=None,
):
    """Build a RecvLoop with mock collaborators."""
    socket = MagicMock()
    if recvfrom_side_effect is not None:
        socket.recvfrom.side_effect = recvfrom_side_effect

    codec = MagicMock()
    if codec_unpack_side_effect is not None:
        codec.unpack.side_effect = codec_unpack_side_effect
    elif codec_unpack_return is not None:
        codec.unpack.return_value = codec_unpack_return
    codec.pack.return_value = b"packed"

    register_uc = MagicMock()
    if register_uc_return is not None:
        register_uc.return_value = register_uc_return
    else:
        register_uc.return_value = {"type": "hello_ack"}

    registry = MagicMock()
    if registry_get is not None:
        registry.get_by_pid.side_effect = registry_get
    else:
        registry.get_by_pid.return_value = None

    if queue is None:
        queue = CentralQueue()

    if stats is None:
        stats = {}

    loop = RecvLoop(
        socket=socket,
        codec=codec,
        register_uc=register_uc,
        registry=registry,
        queue=queue,
        stats=stats,
        enqueue_fn=enqueue_fn,
    )
    return loop, socket, codec, register_uc, registry, queue, stats


# ---------------------------------------------------------------------------
# Two-iteration helper: first call returns data, second raises OSError
# to break the loop cleanly.
# ---------------------------------------------------------------------------

def _two_shot(data: bytes, addr: str = "client.sock"):
    """Return a recvfrom side_effect list: one data tuple then OSError."""
    results = iter([(data, addr), OSError("socket closed")])

    def side_effect():
        val = next(results)
        if isinstance(val, Exception):
            raise val
        return val

    return side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecvLoopDecoding:
    @pytest.mark.asyncio
    async def test_recv_loop_reads_datagram_and_decodes(self):
        """
        Given a socket that returns one datagram then raises OSError,
        When run() is called,
        Then codec.unpack is called with the raw bytes.
        """
        # Arrange
        raw = b"\x81\xa4type\xa5hello"
        decoded = {"type": "hello", "pid": 1, "config_hash": "abc", "service": "svc"}
        loop, socket, codec, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(raw),
            codec_unpack_return=decoded,
        )

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        codec.unpack.assert_called_once_with(raw)

    @pytest.mark.asyncio
    async def test_decode_error_increments_stats_not_crash(self):
        """
        Given codec.unpack raises CodecError,
        When run() processes that datagram,
        Then stats['decode_errors'] is incremented and loop continues (no re-raise).
        """
        # Arrange
        raw = b"\xc1"  # invalid msgpack
        stats: dict = {}

        def unpack_side_effect(data):
            raise CodecError("bad data")

        loop, socket, codec, *_, _, stats = _make_loop(
            recvfrom_side_effect=_two_shot(raw),
            codec_unpack_side_effect=unpack_side_effect,
            stats=stats,
        )

        # Act — OSError from second recvfrom terminates the loop
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        assert stats.get("decode_errors") == 1


class TestHelloRouting:
    @pytest.mark.asyncio
    async def test_hello_routes_to_register_uc(self):
        """
        Given a decoded message with type='hello',
        When _route is called,
        Then register_uc is called with hello=msg and sender_addr.
        """
        # Arrange
        hello_msg = {"type": "hello", "pid": 7, "config_hash": "abc", "service": "svc"}
        loop, socket, codec, register_uc, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=hello_msg,
        )

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        register_uc.assert_called_once_with(hello=hello_msg, sender_addr="client.sock")

    @pytest.mark.asyncio
    async def test_hello_reply_sent_to_sender(self):
        """
        Given register_uc returns an ack dict,
        When _route processes hello,
        Then socket.sendto is called with packed ack and sender addr.
        """
        # Arrange
        hello_msg = {"type": "hello", "pid": 7, "config_hash": "abc", "service": "svc"}
        ack = {"type": "hello_ack", "sidecar_pid": 1, "client_id": 7}
        loop, socket, codec, register_uc, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=hello_msg,
            register_uc_return=ack,
        )
        codec.pack.return_value = b"packed_ack"

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        codec.pack.assert_called_once_with(ack)
        socket.sendto.assert_called_once_with(b"packed_ack", "client.sock")

    @pytest.mark.asyncio
    async def test_hello_reject_sent_on_config_mismatch(self):
        """
        Given register_uc returns a reject dict (invariant I8),
        When _route processes hello,
        Then socket.sendto is called with packed reject and sender addr.
        """
        # Arrange
        hello_msg = {"type": "hello", "pid": 99, "config_hash": "wrong", "service": "svc"}
        reject = {"type": "reject", "reason": "config_hash mismatch"}
        loop, socket, codec, register_uc, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=hello_msg,
            register_uc_return=reject,
        )
        codec.pack.return_value = b"packed_reject"

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        codec.pack.assert_called_once_with(reject)
        socket.sendto.assert_called_once_with(b"packed_reject", "client.sock")


class TestEventRouting:
    @pytest.mark.asyncio
    async def test_known_pid_event_enqueued(self):
        """
        Given a message with a pid registered in the registry,
        When _route processes it with an injected enqueue_fn,
        Then CentralQueue.enqueue is called with a QueueItem containing
        an enriched payload with 'action' and 'fingerprint' keys.
        """
        # Arrange
        event_msg = {"type": "crash", "pid": 42, "data": "boom"}
        registered_client = MagicMock()  # non-None sentinel

        queue = CentralQueue()
        loop, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=event_msg,
            registry_get=lambda pid: registered_client if pid == 42 else None,
            queue=queue,
            enqueue_fn=_make_enqueue_fn(queue),
        )

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert — dequeue and check enriched payload
        item = queue.dequeue()
        assert item is not None
        assert item.payload["type"] == "crash"
        assert item.payload["pid"] == 42
        assert item.payload["data"] == "boom"
        assert "action" in item.payload
        assert "fingerprint" in item.payload

    @pytest.mark.asyncio
    async def test_unknown_pid_increments_stats(self):
        """
        Given a message with pid not in the registry,
        When _route processes it,
        Then stats['unknown_client_messages'] is incremented.
        """
        # Arrange
        event_msg = {"type": "crash", "pid": 99}
        stats: dict = {}
        loop, *_, stats = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=event_msg,
            registry_get=lambda pid: None,
            stats=stats,
        )

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        assert stats.get("unknown_client_messages") == 1

    @pytest.mark.asyncio
    async def test_queue_full_drops_event(self):
        """
        Given a known-pid event and a full queue (max_size=0),
        When enqueue returns False,
        Then stats['queue_full_drops'] is incremented (no crash).
        """
        # Arrange
        event_msg = {"type": "crash", "pid": 42, "severity": "critical"}
        registered_client = MagicMock()
        stats: dict = {}

        # Use a CentralQueue with max_size=0 — will always reject
        # Actually max_size=0 doesn't exist; use a mock that returns False
        queue = MagicMock()
        queue.enqueue.return_value = False

        loop, *_, stats = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=event_msg,
            registry_get=lambda pid: registered_client if pid == 42 else None,
            queue=queue,
            stats=stats,
        )

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        assert stats.get("queue_full_drops") == 1


class TestDedupClassify:
    @pytest.mark.asyncio
    async def test_event_enqueued_with_dedup_action(self):
        """
        Given a registered client sends an event and enqueue_fn uses a dedup mock,
        When recv loop routes it,
        Then the enqueued item contains 'action' and 'fingerprint' from dedup classify.
        """
        # Arrange
        event_msg = {"type": "crash", "pid": 42, "severity": "error", "data": "boom"}
        registered_client = MagicMock()
        queue = CentralQueue()

        dedup_cache = MagicMock()
        dedup_cache.classify.return_value = "new_alert"
        fingerprint_fn = MagicMock(return_value="fp-abc123")

        loop, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=event_msg,
            registry_get=lambda pid: registered_client if pid == 42 else None,
            queue=queue,
            enqueue_fn=_make_enqueue_fn(queue, dedup_cache=dedup_cache),
        )
        loop._fingerprint_fn = fingerprint_fn

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert — dequeue and check
        item = queue.dequeue()
        assert item is not None
        assert item.payload["action"] == "new_alert"
        assert item.payload["fingerprint"] == "fp-abc123"
        # Original msg is NOT mutated
        assert "action" not in event_msg
        assert "fingerprint" not in event_msg

    @pytest.mark.asyncio
    async def test_event_enqueued_without_dedup_defaults_to_new_alert(self):
        """
        Given a registered client sends an event and enqueue_fn has no dedup,
        When recv loop routes it,
        Then the enqueued item contains action='new_alert' and fingerprint=None.
        """
        # Arrange
        event_msg = {"type": "crash", "pid": 42}
        registered_client = MagicMock()
        queue = CentralQueue()

        loop, *_ = _make_loop(
            recvfrom_side_effect=_two_shot(b"data"),
            codec_unpack_return=event_msg,
            registry_get=lambda pid: registered_client if pid == 42 else None,
            queue=queue,
            enqueue_fn=_make_enqueue_fn(queue),
        )
        # No fingerprint_fn set (defaults to None) -> fingerprint=None

        # Act
        with pytest.raises(OSError):
            await loop.run()

        # Assert
        item = queue.dequeue()
        assert item is not None
        assert item.payload["action"] == "new_alert"
        assert item.payload["fingerprint"] is None


class TestRecvLoopLifecycle:
    @pytest.mark.asyncio
    async def test_stop_terminates_loop(self):
        """
        Given a running loop,
        When stop() is called (simulated via OSError with _running=False),
        Then run() exits without raising.
        """
        # Arrange
        stats: dict = {}
        loop_obj, socket, codec, *_ = _make_loop(stats=stats)

        call_count = 0

        def recvfrom_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Trigger stop before second iteration
                loop_obj.stop()
                raise OSError("stopped")
            return (b"data", "addr")

        socket.recvfrom.side_effect = recvfrom_side

        # Act — should NOT propagate the OSError (loop_obj._running is False)
        await loop_obj.run()

        # Assert — completed cleanly
        assert not loop_obj._running
