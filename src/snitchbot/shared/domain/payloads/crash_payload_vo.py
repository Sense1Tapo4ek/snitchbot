"""Crash payload VO + StackFrame VO.

"""
from dataclasses import dataclass
from typing import Literal

CrashOrigin = Literal[
    "sys_excepthook",
    "threading_excepthook",
    "asyncio_handler",
    "signal_handler",
]

@dataclass(frozen=True, slots=True, kw_only=True)
class StackFrame:
    """A single frame in a crash stack trace.

    ``code`` may be ``None`` after truncation step 1 (spec §7).
    """

    file: str
    line: int
    func: str
    code: str | None
    is_user_code: bool

@dataclass(frozen=True, slots=True, kw_only=True)
class CrashPayload:
    """Payload for ``EventKind.CRASH`` events.

    Fields map to spec §3 (crash). Validation (max stack frames, code length,
    origin literal) lives in Task 1.4's validation service — this VO is pure
    data.
    """

    exception_type: str
    message: str
    stack: tuple[StackFrame, ...]
    thread: str
    origin: CrashOrigin
