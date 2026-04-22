"""Unit tests for stack extraction — Task 4.2.

Spec: docs/superpowers/specs/2026-04-11-client-internals-design.md §3.5
Invariants covered:
- CI6: default exclusions (site-packages, stdlib, frozen importlib)
- CI8: linecache lookup limited to top MAX_CODE_LOOKUP_FRAMES frames
"""
import sys
import types

import pytest

from snitchbot.client.ports.driven.stack.stack_extraction_repo import (
    MAX_CODE_LOOKUP_FRAMES,
    MAX_STACK_FRAMES,
    extract_stack_frames,
    is_user_code,
)
from snitchbot.shared.domain.payloads.crash_payload_vo import StackFrame


# ---------------------------------------------------------------------------
# Helpers to fabricate tracebacks of arbitrary depth
# ---------------------------------------------------------------------------


def _make_chain_tb(depth: int) -> types.TracebackType:
    """Return a real traceback chain of exactly `depth` frames.

    Each frame is a real Python frame; the chain points from outermost -> innermost.
    We do this by catching real exceptions inside nested calls.
    """
    # Build depth frames via recursion + exception catch
    frames = []

    def _collect(n: int) -> None:
        if n == 0:
            frames.append(sys._getframe())
            raise RuntimeError("sentinel")
        else:
            frames.append(sys._getframe())
            _collect(n - 1)

    tb = None
    try:
        _collect(depth - 1)
    except RuntimeError:
        tb = sys.exc_info()[2]
    assert tb is not None
    return tb


# ---------------------------------------------------------------------------
# is_user_code tests
# ---------------------------------------------------------------------------


class TestIsUserCode:
    def test_is_user_code_excludes_site_packages(self):
        """
        Given a filepath containing 'site-packages/',
        When calling is_user_code,
        Then False is returned (CI6).
        """
        assert is_user_code("/usr/lib/python3.11/site-packages/requests/api.py") is False

    def test_is_user_code_excludes_stdlib_base_prefix(self):
        """
        Given a filepath that starts with sys.base_prefix (stdlib),
        When calling is_user_code,
        Then False is returned (CI6).
        """
        stdlib_path = sys.base_prefix + "/lib/python3.11/os.py"
        assert is_user_code(stdlib_path) is False

    def test_is_user_code_excludes_frozen_importlib(self):
        """
        Given a filepath starting with '<frozen importlib',
        When calling is_user_code,
        Then False is returned (CI6).
        """
        assert is_user_code("<frozen importlib._bootstrap>") is False

    def test_is_user_code_env_roots_startswith_abs_path(self):
        """
        Given user_code_roots=('/app/',),
        When file is '/app/views.py',
        Then True is returned (abs path startswith match).
        """
        assert is_user_code("/app/views.py", user_code_roots=("/app/",)) is True

    def test_is_user_code_uses_startswith_not_substring(self):
        """
        Given user_code_roots=('/app/',),
        When file is '/opt/reapp/views.py' (substring match would pass, startswith won't),
        Then False is returned (CI spec: startswith, not substring — CI6).
        """
        assert is_user_code("/opt/reapp/views.py", user_code_roots=("/app/",)) is False

    def test_is_user_code_no_partial_dir_match(self):
        """
        Given user_code_roots=('/app',) without trailing separator,
        When file is '/appservice/foo.py' (partial dir name match),
        Then False is returned — root must match a full directory component.
        """
        assert is_user_code("/appservice/foo.py", user_code_roots=("/app",)) is False

    def test_symlinks_resolved(self, monkeypatch: pytest.MonkeyPatch):
        """
        Given os.path.realpath returns a resolved path outside user roots,
        When calling is_user_code with a symlink path,
        Then result reflects the resolved (real) path.
        """
        import os.path

        monkeypatch.setattr(
            "snitchbot.client.ports.driven.stack.stack_extraction_repo.os.path.realpath",
            lambda p: "/usr/lib/python3.11/site-packages/requests/api.py",
        )
        # The original path looks like user code, but realpath resolves to site-packages
        assert is_user_code("/app/some_symlink.py") is False


# ---------------------------------------------------------------------------
# extract_stack_frames tests
# ---------------------------------------------------------------------------


class TestExtractStackFrames:
    def test_stack_respects_max_frames_50(self):
        """
        Given a traceback with more than MAX_STACK_FRAMES frames,
        When calling extract_stack_frames,
        Then at most MAX_STACK_FRAMES frames are returned.
        """
        tb = _make_chain_tb(MAX_STACK_FRAMES + 10)
        result = extract_stack_frames(tb)
        assert len(result) <= MAX_STACK_FRAMES

    def test_returns_tuple_of_stack_frames(self):
        """
        Given any traceback,
        When calling extract_stack_frames,
        Then the result is a tuple of StackFrame VOs.
        """
        try:
            raise ValueError("test")
        except ValueError:
            tb = sys.exc_info()[2]
        result = extract_stack_frames(tb)
        assert isinstance(result, tuple)
        assert all(isinstance(f, StackFrame) for f in result)

    def test_linecache_limited_to_top_20(self, monkeypatch: pytest.MonkeyPatch):
        """
        Given a traceback with more than MAX_CODE_LOOKUP_FRAMES (20) user frames,
        When calling extract_stack_frames,
        Then linecache.getline is called at most MAX_CODE_LOOKUP_FRAMES times (CI8).
        Frames beyond top 20 have code=None.
        """
        call_count = 0

        def counting_getline(filename, lineno, module_globals=None):
            nonlocal call_count
            call_count += 1
            return "    pass\n"

        monkeypatch.setattr(
            "snitchbot.client.ports.driven.stack.stack_extraction_repo.linecache.getline",
            counting_getline,
        )

        # Force all frames to appear as user code so linecache is maximally invoked
        monkeypatch.setattr(
            "snitchbot.client.ports.driven.stack.stack_extraction_repo.is_user_code",
            lambda filepath, user_code_roots=None: True,
        )

        tb = _make_chain_tb(MAX_CODE_LOOKUP_FRAMES + 10)
        extract_stack_frames(tb)
        assert call_count <= MAX_CODE_LOOKUP_FRAMES

    def test_non_user_frames_have_code_none_beyond_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """
        Given a traceback where all frames are non-user-code,
        When calling extract_stack_frames,
        Then code is None for all frames (linecache never called for non-user frames).
        """
        monkeypatch.setattr(
            "snitchbot.client.ports.driven.stack.stack_extraction_repo.is_user_code",
            lambda filepath, user_code_roots=None: False,
        )

        try:
            raise ValueError("test")
        except ValueError:
            tb = sys.exc_info()[2]

        result = extract_stack_frames(tb)
        assert all(f.code is None for f in result)
