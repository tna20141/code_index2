# Tests for the query-view fence extractor. The prompt requires ONE ```python fenced block; we extract the
# content between the fences (discarding any prose outside) and REJECT (None) a fence-less response so the
# caller regenerates. The cached value is stitched verbatim, so extraction must be exact.

from src.services.spread.query_view import _extract_fenced


def test_extracts_fenced_and_drops_leading_preamble():
    raw = ("The function is straightforward. Here's the inlined version:\n\n"
           "```python\nasync def count_shops_using(x):\n    return 1\n```")
    assert _extract_fenced(raw) == "async def count_shops_using(x):\n    return 1"


def test_extracts_bare_fence():
    assert _extract_fenced("```\nx = 1\n```") == "x = 1"


def test_discards_trailing_prose_after_fence():
    assert _extract_fenced("```python\ndef g(): pass\n```\nHope this helps!") == "def g(): pass"


def test_preserves_internal_indentation():
    raw = "```python\ndef f():\n    if x:\n        return 1\n```"
    assert _extract_fenced(raw) == "def f():\n    if x:\n        return 1"


def test_unclosed_fence_extracts_to_end():
    # A missing closing fence still yields the code after the opening fence (defensive).
    assert _extract_fenced("```python\nasync def f():\n    return 1") == "async def f():\n    return 1"


def test_no_fence_is_rejected():
    # The new contract: a response with no fence is REJECTED (None) so the caller regenerates -- even if it
    # is otherwise clean code. This is what closes the old hole where fence-less prose was cached verbatim.
    assert _extract_fenced("Now I have enough context.\n\nasync def f():\n    return 1") is None
    assert _extract_fenced("def f():\n    return 2") is None
