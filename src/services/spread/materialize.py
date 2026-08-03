# Intentions: turn a resolved definition into its readable source block -- the span body PLUS the leading
# intention-comment/decorator block above the `def` (docstrings and inline comments come free, they live
# inside the span). The upward scan is what captures evolix's `# Intentions:`/`# References:` comments and
# the # ci:trivial marker. Pure file I/O, resolver-agnostic. References: docs/spec.md section 2.

from src.services.spread.lsp import Span


def _read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def _is_leading_line(line: str) -> bool:
    # [Pure] a line that belongs to the def's leading block: a comment, a decorator, or blank (blanks are
    # kept only between comment/decorator lines -- the scan stops at the first CODE line above).
    stripped = line.strip()
    return stripped == "" or stripped.startswith(("#", "@"))


def _scan_leading(lines: list[str], def_idx: int) -> list[str]:
    """[Pure] The comment/decorator block immediately above the def line (0-based def_idx). Walk upward while
    lines are comments/decorators/blanks; stop at the first code line. Trailing blank lines (a gap before the
    def) are trimmed so we don't drag in unrelated whitespace. Returns lines in source order."""
    i = def_idx - 1
    collected: list[str] = []
    while i >= 0 and _is_leading_line(lines[i]):
        collected.append(lines[i])
        i -= 1
    collected.reverse()
    # drop leading blank-only rows (the gap separating this block from code above)
    while collected and collected[0].strip() == "":
        collected = collected[1:]
    return collected


def read_leading(path: str, def_line: int) -> list[str]:
    """The leading comment/decorator lines above the def at `def_line` (1-based). Used by boundary.is_trivial
    (scan for # ci:trivial) and to prepend intention-comments to a materialized node."""
    lines = _read_lines(path)
    return _scan_leading(lines, def_line - 1)


def read_body(path: str, span: Span) -> list[str]:
    """The def's source lines over `span` (1-based inclusive). Docstrings + inline comments included (they
    live in the span)."""
    lines = _read_lines(path)
    return lines[span["start_line"] - 1:span["end_line"]]


def read_block(path: str, def_line: int, span: Span) -> list[str]:
    """The full readable block for a node: leading comment/decorator lines + the body span."""
    return read_leading(path, def_line) + read_body(path, span)
