"""Unit tests for progressive_truncation_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §7, §8, R6.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.5.
"""
from snitchbot.sidecar.pipeline.domain.services.progressive_truncation_service import (
    truncate_rendered,
)

# ---------------------------------------------------------------------------
# Helpers to build HTML fragments that mimic the rendered alert format
# ---------------------------------------------------------------------------

def _make_html(
    *,
    header: str = "🔴 <b>crash</b> · orders-api · <code>a1b2c3</code>",
    title: str = "<b>DatabaseConnectionError</b>: connection refused",
    details: str = "<b>Details</b>\n  time  14:42:10 UTC",
    context: str | None = None,
    extras: str | None = None,
    stack: str | None = None,
) -> str:
    """Compose a rendered alert HTML string from individual blocks."""
    parts = [header, title, details]
    if context is not None:
        parts.append(context)
    if extras is not None:
        parts.append(extras)
    if stack is not None:
        parts.append(stack)
    return "\n\n".join(parts)


def _make_context_block(entries: list[tuple[str, str]], value_len: int = 80) -> str:
    lines = ["<b>Context</b>"]
    for k, v in entries:
        v_shown = v[:value_len] if len(v) > value_len else v
        lines.append(f"  {k}  {v_shown}")
    return "\n".join(lines)


def _make_extras_block(entries: list[tuple[str, str]], value_len: int = 80) -> str:
    lines = ["<b>Extras</b>"]
    for k, v in entries:
        v_shown = v[:value_len] if len(v) > value_len else v
        lines.append(f"  {k}  {v_shown}")
    return "\n".join(lines)


def _make_stack_block(frames: list[tuple[str, str]]) -> str:
    """Build a <pre>-wrapped stack block with (location, code_line) frames."""
    lines = ["<b>Stack</b> (top user frames)", "<pre>"]
    for loc, code in frames:
        lines.append(loc)
        lines.append(f"  {code}")
    lines.append("</pre>")
    return "\n".join(lines)


def _make_stack_block_no_code(frames: list[str]) -> str:
    """Stack block where code lines have already been stripped."""
    lines = ["<b>Stack</b> (top user frames)", "<pre>"]
    lines.extend(frames)
    lines.append("</pre>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoTruncation:
    def test_under_4096_no_truncation(self) -> None:
        """
        Given rendered HTML shorter than 4096 chars,
        When truncate_rendered() is called,
        Then the string is returned unchanged.
        """
        html = _make_html()
        assert len(html) < 4096
        result = truncate_rendered(html)
        assert result == html


class TestStep1StripStackCodeLines:
    def test_step1_strips_stack_code_lines(self) -> None:
        """
        Given rendered HTML that exceeds 4096 only due to code lines in the stack block,
        When truncate_rendered() is called,
        Then code lines (indented lines under location lines) are removed from the stack block.
        """
        # Use distinct characters for code lines vs padding so assertions are unambiguous
        code_line_marker = "CODELINE_UNIQUE_MARKER_" + "Q" * 100
        frames = [
            ("app/db/pool.py:47 in acquire()", code_line_marker),
            ("app/services/orders.py:88 in fetch_all()", "CODELINE2_" + "W" * 100),
            ("app/routes/orders.py:12 in list_orders()", "CODELINE3_" + "E" * 100),
        ]
        stack = _make_stack_block(frames)
        # Pad details to push total over 4096 (using "P" chars, not Q/W/E)
        padding = "P" * (4096 - len(_make_html(stack=stack)) + 100)
        html = _make_html(
            details=f"<b>Details</b>\n  time  14:42:10 UTC\n  pad  {padding}",
            stack=stack,
        )
        result = truncate_rendered(html)
        assert len(result) <= 4096
        # Code lines (indented lines under location lines) should be gone
        assert "CODELINE_UNIQUE_MARKER_" not in result
        assert "CODELINE2_" not in result
        assert "CODELINE3_" not in result
        # Location lines must survive
        assert "app/db/pool.py:47 in acquire()" in result


class TestStep2ContextValues:
    def test_step2_reduces_context_values_80_40_20(self) -> None:
        """
        Given rendered HTML that still exceeds 4096 after step 1,
        When truncate_rendered() is called,
        Then context values are first reduced to 40, then to 20 chars.
        """
        long_val = "v" * 80
        ctx = _make_context_block([("trace_id", long_val), ("user_id", long_val)])
        # Make total length > 4096 using a big title
        big_title = "<b>Error</b>: " + "t" * 3800
        html = _make_html(title=big_title, context=ctx)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        # Values should be truncated
        assert "v" * 80 not in result


class TestStep3ExtrasValues:
    def test_step3_extras_values_same(self) -> None:
        """
        Given rendered HTML that requires extras values reduction,
        When truncate_rendered() is called,
        Then extras values are reduced from 80->40->20 chars just like context.
        """
        long_val = "e" * 80
        extras = _make_extras_block([("query", long_val), ("duration_ms", long_val)])
        big_title = "<b>Error</b>: " + "t" * 3800
        html = _make_html(title=big_title, extras=extras)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        assert "e" * 80 not in result


class TestStep4ContextEntries:
    def test_step4_context_entries_kept_first_3(self) -> None:
        """
        Given rendered HTML with many context entries that still exceeds 4096,
        When truncate_rendered() is called,
        Then only the first 3 context entries are kept.
        """
        entries = [(f"key{i}", "v" * 20) for i in range(10)]
        ctx = _make_context_block(entries)
        big_title = "<b>Error</b>: " + "t" * 3900
        html = _make_html(title=big_title, context=ctx)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        # After dropping entries, at most 3 keys should remain
        remaining_keys = [f"key{i}" for i in range(10) if f"key{i}" in result]
        assert len(remaining_keys) <= 3
        # First keys must be the ones kept (first 3)
        for i in range(min(3, len(remaining_keys))):
            assert f"key{i}" in result


class TestStep5ExtrasEntries:
    def test_step5_extras_entries_kept_first_3(self) -> None:
        """
        Given rendered HTML with many extras entries that still exceeds 4096,
        When truncate_rendered() is called,
        Then only the first 3 extras entries are kept.
        """
        entries = [(f"param{i}", "w" * 20) for i in range(10)]
        extras = _make_extras_block(entries)
        big_title = "<b>Error</b>: " + "t" * 3900
        html = _make_html(title=big_title, extras=extras)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        remaining = [f"param{i}" for i in range(10) if f"param{i}" in result]
        assert len(remaining) <= 3


class TestStep6StackFrames:
    def test_step6_stack_frames_3_to_2_to_1(self) -> None:
        """
        Given rendered HTML where stack frame reduction is needed,
        When truncate_rendered() is called,
        Then stack frame count is reduced from 3->2->1.
        """
        # Build a very long stack with 3 frames (no code lines, already stripped)
        frames = [
            "app/db/pool.py:47 in acquire()",
            "app/services/orders.py:88 in fetch_all()",
            "app/routes/orders.py:12 in list_orders()",
        ]
        stack = _make_stack_block_no_code(frames)
        big_title = "<b>Error</b>: " + "t" * 3950
        html = _make_html(title=big_title, stack=stack)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        # At most 1 frame location should remain (most aggressive reduction)
        location_count = sum(1 for f in frames if f in result)
        assert location_count <= 2  # reduced from 3


class TestStep7Title:
    def test_step7_title_message_to_200(self) -> None:
        """
        Given rendered HTML where the title is very long,
        When truncate_rendered() is called,
        Then the title text is truncated to 200 chars.
        """
        long_message = "m" * 500
        big_title = f"<b>Error</b>: {long_message}"
        html = _make_html(title=big_title)
        # Pad details to make it exceed 4096
        html = _make_html(
            title=big_title,
            details="<b>Details</b>\n  time  14:42:10 UTC\n  pad  " + "p" * 3500,
        )
        result = truncate_rendered(html)
        assert len(result) <= 4096
        assert "m" * 500 not in result


class TestStep8DropStackBlock:
    def test_step8_drop_stack_block(self) -> None:
        """
        Given rendered HTML where even step 1-7 reductions are insufficient,
        When truncate_rendered() is called,
        Then the entire Stack block is dropped.
        """
        stack = _make_stack_block_no_code(["app/db/pool.py:47 in acquire()"])
        # Title exactly 200 chars after step-7 truncation, plus a big details pad
        # and a stack block — combined they exceed 4096.
        big_title = "<b>Error</b>: " + "t" * 200
        # Pad details to push the total above 4096 so stack drop is needed
        details = "<b>Details</b>\n  time  14:42:10 UTC\n  pad  " + "p" * 3900
        html = _make_html(title=big_title, details=details, stack=stack)
        assert len(html) > 4096, "test pre-condition: html must exceed 4096"
        result = truncate_rendered(html)
        assert len(result) <= 4096
        assert "<b>Stack</b>" not in result


class TestStep9DropContextBlock:
    def test_step9_drop_context_block(self) -> None:
        """
        Given rendered HTML where even dropping the stack block is not enough,
        When truncate_rendered() is called,
        Then the entire Context block is dropped.
        """
        ctx = _make_context_block([("trace_id", "abc123")])
        # Use details pad (untouchable) to push total over 4096
        details = "<b>Details</b>\n  time  14:42:10 UTC\n  pad  " + "p" * 4000
        html = _make_html(details=details, context=ctx)
        assert len(html) > 4096, "test pre-condition: html must exceed 4096"
        result = truncate_rendered(html)
        assert len(result) <= 4096
        assert "<b>Context</b>" not in result


class TestStep10DropExtrasBlock:
    def test_step10_drop_extras_block(self) -> None:
        """
        Given rendered HTML where even dropping stack+context is not enough,
        When truncate_rendered() is called,
        Then the entire Extras block is dropped.
        """
        extras = _make_extras_block([("query", "SELECT * FROM orders")])
        # Use details pad (untouchable) to push total over 4096
        details = "<b>Details</b>\n  time  14:42:10 UTC\n  pad  " + "p" * 4000
        html = _make_html(details=details, extras=extras)
        assert len(html) > 4096, "test pre-condition: html must exceed 4096"
        result = truncate_rendered(html)
        assert len(result) <= 4096
        assert "<b>Extras</b>" not in result


class TestNeverTruncatesHeaderDetailsButtons:
    def test_never_truncates_header_details_buttons(self) -> None:
        """
        Given rendered HTML that needs truncation,
        When truncate_rendered() is called,
        Then Header, Details block, and any Buttons section are never removed.
        (Spec §8: these always fit under 500 chars combined.)
        """
        header = "🔴 <b>crash</b> · orders-api · <code>a1b2c3</code>"
        details = "<b>Details</b>\n  time  14:42:10 UTC\n  pid  101"
        # Large title forces truncation
        big_title = "<b>Error</b>: " + "t" * 4000
        html = _make_html(header=header, title=big_title, details=details)
        result = truncate_rendered(html)
        assert len(result) <= 4096
        # Header content must survive
        assert "a1b2c3" in result
        assert "🔴" in result
        # Details block must survive
        assert "<b>Details</b>" in result


class TestAlwaysFits4096:
    def test_always_fits_4096_even_with_pathological_input(self) -> None:
        """
        Given an HTML string with every block maximally large (pathological input),
        When truncate_rendered() is called,
        Then the result always fits within 4096 chars (R6).
        """
        # Worst case: all blocks filled with max-length strings
        ctx = _make_context_block([(f"key{i}", "v" * 200) for i in range(20)])
        extras = _make_extras_block([(f"param{i}", "e" * 200) for i in range(20)])
        frames = [
            (f"app/module/file{i}.py:{i * 10} in func_{i}()", "x" * 200)
            for i in range(10)
        ]
        stack = _make_stack_block(frames)
        html = _make_html(
            title="<b>VeryLongError</b>: " + "t" * 500,
            details="<b>Details</b>\n  time  14:42:10 UTC\n  pad  " + "p" * 500,
            context=ctx,
            extras=extras,
            stack=stack,
        )
        result = truncate_rendered(html)
        assert len(result) <= 4096
