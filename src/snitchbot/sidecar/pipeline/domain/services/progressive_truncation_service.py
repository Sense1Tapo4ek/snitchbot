"""Progressive truncation of rendered alert HTML.

Sidecar-side: works on the already-rendered HTML string to fit within
Telegram's 4096-char message limit.

Invariant R6: message always fits 4096 chars even with pathological input.

Steps (lowest priority removed first):
  1. Strip code lines from stack blocks
  2. Reduce context values 80->40->20 chars
  3. Reduce extras values 80->40->20 chars
  4. Keep only first 3 context entries
  5. Keep only first 3 extras entries
  6. Reduce stack frames 3->2->1
  7. Title/message to 200 chars
  8. Drop stack block entirely
  9. Drop context block entirely
  10. Drop extras block entirely

Never truncates: Header (first paragraph), Details block, Buttons.
"""
import re

from snitchbot.shared.constants import TG_MESSAGE_LIMIT


# Matches the entire stack block: <b>Stack</b>...until a double-newline or end
_STACK_BLOCK_RE = re.compile(
    r"<b>Stack</b>[^\n]*\n<pre>(.*?)</pre>",
    re.DOTALL,
)

# Matches the entire Context block including its header line
_CONTEXT_BLOCK_RE = re.compile(
    r"<b>Context</b>\n(?:[ \t]+\S.*\n?)*",
    re.MULTILINE,
)

# Matches the entire Extras block
_EXTRAS_BLOCK_RE = re.compile(
    r"<b>Extras</b>\n(?:[ \t]+\S.*\n?)*",
    re.MULTILINE,
)

# A context/extras value line: "  key  value"
_KV_LINE_RE = re.compile(r"^([ \t]+\S+[ \t]+)(.+)$")

# Inside a <pre> stack block, a "code" line is indented (starts with spaces)
# while a location line is not indented (starts with non-space content)
_STACK_CODE_LINE_RE = re.compile(r"^[ \t]+\S.*$", re.MULTILINE)

# Location line inside stack block (not indented)
_STACK_LOCATION_LINE_RE = re.compile(r"^[^ \t<].*$", re.MULTILINE)

def _fits(html: str, max_len: int) -> bool:
    return len(html) <= max_len


def _strip_stack_code_lines(html: str) -> str:
    """Step 1: remove indented code lines inside <pre>…</pre> stack blocks."""
    def _strip_pre(m: re.Match) -> str:
        pre_content = m.group(1)
        # Remove lines that start with whitespace (code lines)
        cleaned = re.sub(r"^[ \t]+\S.*\n?", "", pre_content, flags=re.MULTILINE)
        prefix = m.group(0)[: m.start(1) - m.start(0)]
        return f"{prefix}{cleaned}</pre>"

    return _STACK_BLOCK_RE.sub(_strip_pre, html)

def _reduce_kv_values(block_content: str, max_val: int) -> str:
    """Reduce values in a key-value block to at most max_val chars per line."""
    lines = block_content.split("\n")
    result = []
    for line in lines:
        m = _KV_LINE_RE.match(line)
        if m:
            prefix, value = m.group(1), m.group(2)
            result.append(prefix + value[:max_val])
        else:
            result.append(line)
    return "\n".join(result)

def _reduce_block_values(html: str, block_re: re.Pattern, max_val: int) -> str:
    """Apply value-length reduction to all lines in the matched block."""
    def _replace(m: re.Match) -> str:
        return _reduce_kv_values(m.group(0), max_val)
    return block_re.sub(_replace, html)

def _keep_first_n_entries(block_content: str, n: int) -> str:
    """Keep only the first n key-value lines in a block (header line stays)."""
    lines = block_content.split("\n")
    header = lines[0]  # e.g. "<b>Context</b>"
    kv_lines = [line for line in lines[1:] if _KV_LINE_RE.match(line)]
    kept = kv_lines[:n]
    other = [line for line in lines[1:] if not _KV_LINE_RE.match(line)]
    return "\n".join([header] + kept + other)

def _trim_block_entries(html: str, block_re: re.Pattern, n: int) -> str:
    def _replace(m: re.Match) -> str:
        return _keep_first_n_entries(m.group(0), n)
    return block_re.sub(_replace, html)

def _reduce_stack_frames(html: str, max_frames: int) -> str:
    """Reduce the number of location lines inside stack <pre> blocks."""
    def _trim_frames(m: re.Match) -> str:
        pre_content = m.group(1)
        # Location lines: non-indented, non-empty inside the pre block
        location_lines = [
            line for line in pre_content.split("\n")
            if line.strip() and not line.startswith(" ") and not line.startswith("\t")
        ]
        # Find which location lines to keep
        kept = set(location_lines[:max_frames])
        result_lines = []
        seen = 0
        for line in pre_content.split("\n"):
            is_loc = line.strip() and not line.startswith(" ") and not line.startswith("\t")
            if is_loc:
                if line in kept and seen < max_frames:
                    result_lines.append(line)
                    seen += 1
                # Skip location lines beyond max_frames
            else:
                result_lines.append(line)
        new_pre = "\n".join(result_lines)
        prefix = m.group(0)[: m.start(1) - m.start(0)]
        return f"{prefix}{new_pre}</pre>"

    return _STACK_BLOCK_RE.sub(_trim_frames, html)

def _truncate_title(html: str, max_title: int = 200) -> str:
    """Step 7: truncate the title line (second paragraph / non-Details bold line)."""
    # The title is the second block (after the header). It may contain <b>...</b>: text
    # We find the first <b>...</b>: ... pattern that is NOT a block header like Details/Stack/etc.
    _block_headers = {"Details", "Context", "Stack", "Extras", "Stuck tasks"}

    def _shorten(m: re.Match) -> str:
        tag_name = m.group(1)
        if tag_name in _block_headers:
            return m.group(0)
        full = m.group(0)
        if len(full) > max_title:
            return full[:max_title]
        return full

    # Match a line that starts a "title" — a bold element followed by optional ": text"
    title_re = re.compile(r"<b>([^<]+)</b>[^\n]*")
    return title_re.sub(_shorten, html)

def _drop_block(html: str, block_re: re.Pattern) -> str:
    """Drop the matched block entirely (replace with empty string, clean up extra newlines)."""
    result = block_re.sub("", html)
    # Clean up runs of 3+ newlines left by removal
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def truncate_rendered(html: str, *, max_len: int = TG_MESSAGE_LIMIT) -> str:
    """Progressive truncation of rendered alert HTML to fit max_len chars.

    Applies steps in order from spec §7, stopping as soon as the string fits.
    Never truncates Header, Details block, or Buttons (spec §8).
    Invariant R6: always returns a string with len() <= max_len.
    """
    if _fits(html, max_len):
        return html

    # Step 1: Strip code lines from stack blocks
    html = _strip_stack_code_lines(html)
    if _fits(html, max_len):
        return html

    # Step 2: Reduce context values 80->40->20
    for val_limit in (40, 20):
        html = _reduce_block_values(html, _CONTEXT_BLOCK_RE, val_limit)
        if _fits(html, max_len):
            return html

    # Step 3: Reduce extras values 80->40->20
    for val_limit in (40, 20):
        html = _reduce_block_values(html, _EXTRAS_BLOCK_RE, val_limit)
        if _fits(html, max_len):
            return html

    # Step 4: Keep only first 3 context entries
    html = _trim_block_entries(html, _CONTEXT_BLOCK_RE, 3)
    if _fits(html, max_len):
        return html

    # Step 5: Keep only first 3 extras entries
    html = _trim_block_entries(html, _EXTRAS_BLOCK_RE, 3)
    if _fits(html, max_len):
        return html

    # Step 6: Reduce stack frames 3->2->1
    for max_frames in (2, 1):
        html = _reduce_stack_frames(html, max_frames)
        if _fits(html, max_len):
            return html

    # Step 7: Truncate title to 200 chars
    html = _truncate_title(html, max_title=200)
    if _fits(html, max_len):
        return html

    # Step 8: Drop stack block entirely
    html = _drop_block(html, _STACK_BLOCK_RE)
    if _fits(html, max_len):
        return html

    # Step 9: Drop context block entirely
    html = _drop_block(html, _CONTEXT_BLOCK_RE)
    if _fits(html, max_len):
        return html

    # Step 10: Drop extras block entirely
    html = _drop_block(html, _EXTRAS_BLOCK_RE)
    if _fits(html, max_len):
        return html

    # Final safety net: hard-truncate (should never reach here with reasonable input)
    return html[:max_len]

__all__ = ["truncate_rendered"]
