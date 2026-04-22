"""Hello handshake service (Task 2.4).

Builds the hello payload and executes the send/recv handshake with the sidecar.

Design: accepts callables for send/recv so the service is testable without real
sockets. ``transport_recv`` takes ``timeout_ms: int`` and returns ``bytes`` on
success, or ``None`` if the deadline expired.

Spec refs: §5.4 (hello/ack), §8.5 (timeout), §8.6 (reject).
"""

from collections.abc import Callable

import msgpack

from snitchbot.client.errors import HandshakeRejectedError, HandshakeTimeoutError
from snitchbot.shared.constants import HANDSHAKE_RESPONSE_TIMEOUT_MS
from snitchbot.shared.domain import AnomalyConfig


def build_hello(
    *,
    pid: int,
    service: str,
    config_hash: str,
    started_at: float,
    anomaly_config: AnomalyConfig,
    role: str = "standalone",
    sample_interval_sec: int = 5,
) -> dict:
    """Return the hello payload dict (wire format, msgpack-friendly).

    Shape (§5.4)::

        {
            "type":          "hello",
            "pid":           <int>,
            "service":       <str>,
            "config_hash":   <str>,
            "started_at":    <float>,
            "role":          <str>,   # "master" | "worker" | "standalone"
            "anomaly_config": {<canonical dict from AnomalyConfig.resolve()>},
        }

    The ``anomaly_config`` value is always the canonical dict produced by
    :meth:`AnomalyConfig.resolve` — never the raw VO object.
    """
    return {
        "type": "hello",
        "pid": pid,
        "service": service,
        "config_hash": config_hash,
        "started_at": started_at,
        "role": role,
        "anomaly_config": anomaly_config.resolve(),
        "sample_interval_sec": sample_interval_sec,
    }


def perform_handshake(
    *,
    transport_send: Callable[[bytes], None],
    transport_recv: Callable[[int], bytes | None],
    hello_payload: dict,
    timeout_ms: int = HANDSHAKE_RESPONSE_TIMEOUT_MS,
) -> dict:
    """Pack and send *hello_payload*, then wait for an ack from the sidecar.

    Args:
        transport_send: Callable that accepts raw bytes and delivers them to
            the sidecar (no return value expected).
        transport_recv: Callable that accepts ``timeout_ms`` and returns the
            raw ack bytes, or ``None`` if the deadline expired.
        hello_payload: The dict produced by :func:`build_hello`.
        timeout_ms: Milliseconds to wait for the ack response.  Defaults to
            ``HANDSHAKE_RESPONSE_TIMEOUT_MS``.

    Returns:
        The decoded ack dict (contains at minimum ``type="hello_ack"``,
        ``sidecar_pid``, and ``sidecar_lib_version``).

    Raises:
        HandshakeTimeoutError: ``transport_recv`` returned ``None``.
        HandshakeRejectedError: Sidecar replied with ``type="reject"``.
    """
    raw_hello = msgpack.packb(hello_payload, use_bin_type=True)
    transport_send(raw_hello)

    raw_response = transport_recv(timeout_ms)

    if raw_response is None:
        raise HandshakeTimeoutError(
            f"No hello_ack received within {timeout_ms} ms"
        )

    ack = msgpack.unpackb(raw_response, raw=False)

    if ack.get("type") == "reject":
        reason = ack.get("reason", "")
        raise HandshakeRejectedError(reason=reason)

    return ack
