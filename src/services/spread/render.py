# Intentions: stitch materialized blocks into the reading-only spread artifact -- name-matched
# spread-begin/spread-end markers around each descended callee, in one of two render modes (indented vs
# flat). Structure is recovered from the marker pairs, not indentation (indentation is garnish). Pure.
# References: docs/spec.md section 2.

from src.constants import SPREAD_BEGIN, SPREAD_END, SpreadMode


def _indent(lines: list[str], prefix: str) -> list[str]:
    # [Pure] left-pad every line by `prefix` (constant shift -- preserves the block's internal relative
    # indentation; we do NOT reflow, so multi-line string contents keep their shape).
    return [prefix + line if line else line for line in lines]


def begin_marker(ref: str) -> str:
    """`# && spread-begin: <path-from-root>:<name>` -- opens a descended callee's block."""
    return f"{SPREAD_BEGIN} {ref}"


def end_marker(ref: str) -> str:
    """`# && spread-end: <path-from-root>:<name>` -- closes it (name-matched to the begin)."""
    return f"{SPREAD_END} {ref}"


def wrap(ref: str, block: list[str], mode: SpreadMode, indent_prefix: str = "") -> list[str]:
    """Bracket a callee's materialized `block` with begin/end markers. In INDENTED mode the whole thing is
    left-padded by `indent_prefix` (the caller's indentation, so it nests visually); in FLAT mode the block
    keeps its natural indentation and structure rests on the markers alone."""
    wrapped = [begin_marker(ref), *block, end_marker(ref)]
    if mode == SpreadMode.INDENTED and indent_prefix:
        return _indent(wrapped, indent_prefix)
    return wrapped
