"""Stack extraction driven port — Task 4.2.

Reads filesystem via linecache and checks sys.base_prefix.
This is a DRIVEN PORT (not domain) because it performs I/O.

Invariants:
- CI6: default exclusions (site-packages, stdlib, frozen importlib)
- CI8: linecache lookup limited to top MAX_CODE_LOOKUP_FRAMES frames
"""
import linecache
import logging
import os.path
import sys
import types

from snitchbot.shared.domain.payloads.crash_payload_vo import StackFrame

logger = logging.getLogger("snitchbot.client.ports.driven.stack.stack_extraction_repo")

MAX_STACK_FRAMES: int = 50
MAX_CODE_LOOKUP_FRAMES: int = 20

def is_user_code(
    filepath: str,
    *,
    user_code_roots: tuple[str, ...] | None = None,
) -> bool:
    """Return True if filepath is user code, False if stdlib/site-packages/frozen.

    Default exclusions (CI6):
    - site-packages/
    - sys.base_prefix (stdlib)
    - <frozen importlib...>

    If user_code_roots is provided, the resolved absolute path must startswith
    one of them (abs path, not substring — CI spec). Symlinks are resolved
    before comparison.
    """
    # Check frozen importlib on raw path before realpath (realpath mangles <...> names)
    if filepath.startswith("<frozen"):
        return False  # frozen importlib bootstraps — CI6

    try:
        abs_path = os.path.realpath(filepath)
    except Exception:
        logger.debug("realpath resolution failed", exc_info=True)
        return False

    if user_code_roots is not None:
        return any(
            abs_path.startswith(root if root.endswith(os.sep) else root + os.sep)
            for root in user_code_roots
        )

    # Default heuristic
    if abs_path.startswith(sys.base_prefix):
        return False  # stdlib
    if "site-packages" in abs_path:
        return False  # installed packages
    return True

def extract_stack_frames(
    tb: types.TracebackType | None,
    *,
    user_code_roots: tuple[str, ...] | None = None,
) -> tuple[StackFrame, ...]:
    """Extract StackFrame VOs from a traceback.

    - Max MAX_STACK_FRAMES frames total.
    - linecache lookup only for user frames and only on top MAX_CODE_LOOKUP_FRAMES (CI8).
    - is_user_code set per is_user_code() for each frame.
    - Non-user frames and frames beyond the code-lookup limit get code=None.
    """
    frames: list[StackFrame] = []
    code_lookups_done: int = 0

    while tb is not None and len(frames) < MAX_STACK_FRAMES:
        frame = tb.tb_frame
        filename: str = frame.f_code.co_filename
        lineno: int = tb.tb_lineno
        func: str = frame.f_code.co_name
        user: bool = is_user_code(filename, user_code_roots=user_code_roots)

        code: str | None = None
        if user and code_lookups_done < MAX_CODE_LOOKUP_FRAMES:
            raw = linecache.getline(filename, lineno).strip()
            code = raw[:200] if raw else None
            code_lookups_done += 1

        frames.append(
            StackFrame(
                file=filename,
                line=lineno,
                func=func,
                code=code,
                is_user_code=user,
            )
        )
        tb = tb.tb_next

    return tuple(frames)
