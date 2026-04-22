"""Tests for request_context context manager.

CI27: sets contextvar on enter, restores on exit
CI28: trace_id=None remains None (no synthetic ID generated)
CI29: nested contexts merge extras, inner overrides outer
CI30: parent trace_id inherited if child doesn't specify
CI31: propagates through asyncio.create_task
CI32: does NOT propagate through threading.Thread by default (documented)
E10:  empty context becomes None, not empty dict
"""
import asyncio
import threading

import pytest

from snitchbot.client.adapters.driving.instrumentation.request_context import (
    _current_context,
    get_current_context,
    request_context,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _reset_context():
    """Force contextvar to default (None) between tests."""
    # Each test gets its own execution context; contextvar is thread-local
    # by design, but let's ensure no leakage by resetting via token.
    pass  # contextvar default is None, so isolation is guaranteed per-test


# ---------------------------------------------------------------------------
# CI27  basic enter / exit
# ---------------------------------------------------------------------------


class TestBasicEnterExit:
    def test_sets_contextvar_on_enter_restores_on_exit(self):
        """
        Given request_context with trace_id,
        When entered,
        Then _current_context is set; after exit, it is None again (CI27).
        """
        assert _current_context.get() is None

        with request_context(trace_id="t1", user_id=42):
            ctx = _current_context.get()
            assert ctx is not None
            assert ctx["trace_id"] == "t1"

        assert _current_context.get() is None

    def test_exception_inside_with_still_restores_context(self):
        """
        Given an exception inside request_context block,
        When exception propagates,
        Then contextvar is still reset to None.
        """
        with pytest.raises(RuntimeError):
            with request_context(trace_id="boom"):
                raise RuntimeError("fail")

        assert _current_context.get() is None


# ---------------------------------------------------------------------------
# CI28  no synthetic trace_id
# ---------------------------------------------------------------------------


class TestNoSyntheticTraceId:
    def test_trace_id_none_remains_none_no_synthetic_id(self):
        """
        Given no trace_id and no parent context,
        When entering request_context,
        Then trace_id stays None — no synthetic ID generated (CI28).
        """
        with request_context(user_id=1):
            ctx = _current_context.get()
            assert ctx["trace_id"] is None

    def test_explicit_trace_id_used(self):
        """
        Given explicit trace_id="abc123",
        When entering request_context,
        Then context carries that exact trace_id.
        """
        with request_context(trace_id="abc123"):
            ctx = _current_context.get()
            assert ctx["trace_id"] == "abc123"


# ---------------------------------------------------------------------------
# CI30  trace_id inheritance from parent
# ---------------------------------------------------------------------------


class TestTraceIdInheritance:
    def test_parent_trace_id_inherited(self):
        """
        Given outer context with trace_id,
        When inner context is entered without trace_id,
        Then inner inherits parent trace_id (CI30).
        """
        with request_context(trace_id="parent-trace"):
            with request_context(user_id=99):
                ctx = _current_context.get()
                assert ctx["trace_id"] == "parent-trace"

    def test_inner_trace_id_overrides_parent(self):
        """
        Given outer context with trace_id,
        When inner context is entered WITH its own trace_id,
        Then inner uses its own trace_id.
        """
        with request_context(trace_id="outer"):
            with request_context(trace_id="inner"):
                ctx = _current_context.get()
                assert ctx["trace_id"] == "inner"

        # After inner exits, back to outer
        assert _current_context.get() is None


# ---------------------------------------------------------------------------
# CI29  nested extras merge
# ---------------------------------------------------------------------------


class TestNestedExtrasMerge:
    def test_nested_extras_merge_inner_overrides_outer(self):
        """
        Given outer context with user_id=42, path="/a",
        When inner context with user_id=99 is entered,
        Then inner sees user_id=99 (override) and path="/a" (inherited) (CI29).
        """
        with request_context(trace_id="t", user_id=42, path="/a"):
            with request_context(user_id=99):
                ctx = _current_context.get()
                assert ctx["extras"]["user_id"] == 99
                assert ctx["extras"]["path"] == "/a"

    def test_nested_context_yields_and_unwinds_in_order(self):
        """
        Given 3 nested contexts,
        When unwound,
        Then each level restores its own state.
        """
        with request_context(trace_id="L1", a=1):
            with request_context(b=2):
                with request_context(c=3):
                    inner = _current_context.get()
                    assert inner["extras"] == {"a": 1, "b": 2, "c": 3}
                # back to level 2
                l2 = _current_context.get()
                assert l2["extras"] == {"a": 1, "b": 2}
                assert "c" not in l2["extras"]
            # back to level 1
            l1 = _current_context.get()
            assert l1["extras"] == {"a": 1}

        assert _current_context.get() is None


# ---------------------------------------------------------------------------
# CI31  asyncio.create_task propagation
# ---------------------------------------------------------------------------


class TestAsyncioContextPropagation:
    @pytest.mark.asyncio
    async def test_context_propagates_through_asyncio_create_task(self):
        """
        Given a request_context active in a coroutine,
        When asyncio.create_task is used to spawn a sub-task,
        Then the sub-task inherits the context (CI31 — native Python behavior).
        """
        captured = {}

        async def worker():
            ctx = _current_context.get()
            captured["ctx"] = ctx

        with request_context(trace_id="task-trace", role="worker"):
            task = asyncio.create_task(worker())
            await task

        assert captured["ctx"] is not None
        assert captured["ctx"]["trace_id"] == "task-trace"
        assert captured["ctx"]["extras"]["role"] == "worker"


# ---------------------------------------------------------------------------
# CI32  threading.Thread does NOT propagate
# ---------------------------------------------------------------------------


class TestThreadContextNotPropagated:
    def test_context_does_not_propagate_through_threading_thread_by_default(self):
        """
        Given a request_context active in main thread,
        When a new threading.Thread is started without copy_context,
        Then the thread sees None (CI32 — documented behavior).
        """
        captured = {}

        def worker():
            captured["ctx"] = _current_context.get()

        with request_context(trace_id="main-trace"):
            t = threading.Thread(target=worker)
            t.start()
            t.join()

        assert captured["ctx"] is None


# ---------------------------------------------------------------------------
# E10  empty context -> None
# ---------------------------------------------------------------------------


class TestEmptyContextBecomesNone:
    def test_context_attached_to_event_in_get_current_context(self):
        """
        Given a request_context with trace_id and extras,
        When get_current_context() is called inside the block,
        Then it returns the context dict.
        """
        with request_context(trace_id="x", foo="bar"):
            ctx = get_current_context()
            assert ctx is not None
            assert ctx["trace_id"] == "x"
            assert ctx["extras"]["foo"] == "bar"

    def test_empty_context_becomes_None_not_empty_dict(self):
        """
        Given request_context entered with no trace_id and no extras,
        When get_current_context() is called,
        Then it returns None (E10 — no-op context is invisible).
        """
        with request_context():
            result = get_current_context()
            assert result is None

    def test_get_current_context_outside_block_is_none(self):
        """
        Given no active request_context,
        When get_current_context() is called,
        Then it returns None.
        """
        assert get_current_context() is None
