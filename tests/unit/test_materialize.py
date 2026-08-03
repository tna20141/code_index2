# Unit tests for materialize's leading-comment / body extraction (services/spread/materialize).

from src.services.spread import materialize
from src.services.spread.lsp import Span

_SOURCE = '''import os


# Intentions: do the thing.
# References: nowhere.
@decorator
def target(a, b):
    """Docstring here."""
    return a + b  # inline comment


def other():
    pass
'''


def _write(tmp_path, text):
    p = tmp_path / "mod.py"
    p.write_text(text)
    return str(p)


def test_read_leading_captures_comment_and_decorator_block(tmp_path):
    path = _write(tmp_path, _SOURCE)
    # `def target` is line 7 (1-based).
    leading = materialize.read_leading(path, 7)
    assert leading == ["# Intentions: do the thing.", "# References: nowhere.", "@decorator"]


def test_read_leading_stops_at_code_above(tmp_path):
    path = _write(tmp_path, _SOURCE)
    # blank gap above the comment block is trimmed; the `import os` / blank lines are NOT included.
    leading = materialize.read_leading(path, 7)
    assert "import os" not in leading


def test_read_body_includes_docstring_and_inline_comment(tmp_path):
    path = _write(tmp_path, _SOURCE)
    body = materialize.read_body(path, Span(start_line=7, end_line=9))
    assert body[0] == "def target(a, b):"
    assert '"""Docstring here."""' in body[1]
    assert "# inline comment" in body[2]


def test_no_leading_block(tmp_path):
    path = _write(tmp_path, "def bare():\n    return 1\n")
    assert materialize.read_leading(path, 1) == []
