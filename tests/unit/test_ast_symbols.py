# Tests for the AST-based symbol index (find_symbols) that backs `discover` -- it replaced jedi's
# workspace/symbol, which was INCOMPLETE for common names (returned a partial subset, dropping repo defs).
# These verify completeness (ALL same-named defs found), correct kinds, dir pruning, and robustness.

import os

from src.services.spread import ast_symbols


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def test_finds_all_same_named_defs_across_files(tmp_path):
    root = str(tmp_path)
    _write(root, "svc/a.py", "async def update():\n    return 1\n")
    _write(root, "repo/b.py", "async def update(x):\n    return x\n")
    _write(root, "repo/c.py", "def update():\n    pass\n")
    res = ast_symbols.find_symbols(root, "update")
    # completeness: all THREE are returned (the jedi bug dropped some) -- and sorted by path then line.
    assert [(m["path"], m["line"]) for m in res] == [
        ("repo/b.py", 1), ("repo/c.py", 1), ("svc/a.py", 1)]
    assert all(m["kind"] == "Function" for m in res)


def test_class_and_method_kinds_with_container(tmp_path):
    root = str(tmp_path)
    _write(root, "m.py", "class Foo:\n    def update(self):\n        pass\n\ndef update():\n    pass\n")
    res = ast_symbols.find_symbols(root, "update")
    method = next(m for m in res if m["kind"] == "Method")
    assert method["container"] == "Foo"
    func = next(m for m in res if m["kind"] == "Function")
    assert "container" not in func  # top-level function has no container

    cls = ast_symbols.find_symbols(root, "Foo")
    assert len(cls) == 1 and cls[0]["kind"] == "Class"


def test_skips_dependency_dirs(tmp_path):
    root = str(tmp_path)
    _write(root, "src/real.py", "def fetch():\n    pass\n")
    _write(root, ".venv/lib/dep.py", "def fetch():\n    pass\n")
    _write(root, "node_modules/x.py", "def fetch():\n    pass\n")
    _write(root, "src/__pycache__/cached.py", "def fetch():\n    pass\n")
    res = ast_symbols.find_symbols(root, "fetch")
    assert [m["path"] for m in res] == ["src/real.py"]


def test_unparseable_file_is_skipped_not_fatal(tmp_path):
    root = str(tmp_path)
    _write(root, "good.py", "def target():\n    pass\n")
    _write(root, "broken.py", "def broken(:\n  pass\n")  # syntax error
    res = ast_symbols.find_symbols(root, "target")
    assert [m["path"] for m in res] == ["good.py"]  # good file still found, broken one skipped


def test_nested_function_is_found(tmp_path):
    root = str(tmp_path)
    _write(root, "n.py", "def outer():\n    def helper():\n        pass\n    return helper\n")
    res = ast_symbols.find_symbols(root, "helper")
    assert len(res) == 1 and res[0]["kind"] == "Function" and res[0]["line"] == 2


def test_no_match_returns_empty(tmp_path):
    root = str(tmp_path)
    _write(root, "a.py", "def something():\n    pass\n")
    assert ast_symbols.find_symbols(root, "nonexistent") == []
