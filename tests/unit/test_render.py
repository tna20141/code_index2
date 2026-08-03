# Unit tests for the spread renderer's markers and the two modes (services/spread/render).

from src.constants import SpreadMode
from src.services.spread import render


def test_markers_are_name_matched():
    assert render.begin_marker("f.py:10") == "# && spread-begin: f.py:10"
    assert render.end_marker("f.py:10") == "# && spread-end: f.py:10"


def test_wrap_flat_keeps_natural_indentation():
    block = ["def child():", "    return 1"]
    out = render.wrap("f.py:10", block, SpreadMode.FLAT, indent_prefix="        ")
    assert out == ["# && spread-begin: f.py:10", "def child():", "    return 1", "# && spread-end: f.py:10"]


def test_wrap_indented_left_pads_whole_block():
    block = ["def child():", "    return 1"]
    out = render.wrap("f.py:10", block, SpreadMode.INDENTED, indent_prefix="    ")
    assert out[0] == "    # && spread-begin: f.py:10"
    assert out[1] == "    def child():"
    assert out[2] == "        return 1"  # internal relative indentation preserved (constant shift)
    assert out[3] == "    # && spread-end: f.py:10"


def test_indented_mode_without_prefix_is_flat():
    block = ["x = 1"]
    assert render.wrap("r", block, SpreadMode.INDENTED, indent_prefix="") == [
        "# && spread-begin: r", "x = 1", "# && spread-end: r"]
