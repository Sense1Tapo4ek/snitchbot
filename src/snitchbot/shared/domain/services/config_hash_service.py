"""Config hash & socket path — single source of truth for client and sidecar.

Per sidecar spec §5.1:
- `compute_config_hash(token, chat_id)` returns a deterministic fingerprint
  over the byte stream `token.encode("utf-8") + b"\\x00" + str(chat_id).encode("utf-8")`
  using blake2b(digest_size=6) -> 12-char lowercase hex.
- `compute_socket_path(service, token, chat_id)` returns the UNIX socket path
  in XDG_RUNTIME_DIR if available, otherwise in `/tmp/snitchbot-<uid>/` (mode 0700).

Both client-side discovery and sidecar-side hello validation MUST import
from this module. Duplicating the logic is a known source of token-rotation bugs.
"""
import os
from hashlib import blake2b
from pathlib import Path

__all__ = ["compute_config_hash", "compute_socket_path"]


def compute_config_hash(token: str, chat_id: str | int) -> str:
    """Deterministic 12-hex-char fingerprint for (token, chat_id).

    Uses blake2b(digest_size=6) over the byte stream::

        token.encode("utf-8") + b"\\x00" + str(chat_id).encode("utf-8")

    The null-byte separator prevents boundary-collision attacks
    (e.g. token="a", chat_id="bc" vs token="ab", chat_id="c").

    Both arguments are treated as opaque byte streams; edge characters
    (``\\x00``, ``\\n``, negative chat_id) are safe because blake2b accepts
    arbitrary bytes.

    Args:
        token: The Telegram bot token (or any opaque secret).
        chat_id: The Telegram chat id (``int`` or ``str``).

    Returns:
        12-character lowercase hex string.
    """
    payload = token.encode("utf-8") + b"\x00" + str(chat_id).encode("utf-8")
    return blake2b(payload, digest_size=6).hexdigest()


def compute_socket_path(service: str, token: str, chat_id: str | int) -> Path:
    """Return the UNIX socket path for the ``(service, token, chat_id)`` triple.

    Resolution rules (per sidecar spec §5.1):

    1. If ``$XDG_RUNTIME_DIR`` is set and points to an existing directory,
       use it as the base.
    2. Otherwise, fall back to ``/tmp/snitchbot-<uid>/``, creating it with
       mode ``0o700`` if it does not exist.

    Filename format: ``f"snitchbot-{service}-{config_hash}.sock"``.

    Args:
        service: Logical service name (used in the filename).
        token: The Telegram bot token.
        chat_id: The Telegram chat id.

    Returns:
        Absolute :class:`~pathlib.Path` of the socket.
    """
    fp = compute_config_hash(token, chat_id)

    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and Path(runtime).is_dir():
        base = Path(runtime)
    else:
        base = Path(f"/tmp/snitchbot-{os.getuid()}")
        base.mkdir(mode=0o700, exist_ok=True)

    return base / f"snitchbot-{service}-{fp}.sock"
