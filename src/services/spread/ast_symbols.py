# Intentions: a complete, deterministic name->definitions index for `discover` / spread-by-symbol, built by
# AST-scanning the repo's .py files. Replaces the jedi `workspace/symbol` call, which is INCOMPLETE for common
# names: jedi returns only a small partial subset (e.g. for `update` it returned 3 of the 6 defs, silently
# dropping every repositories/*.py one). A name lookup doesn't need a language server -- it needs a name->sites
# map, and an ast walk produces that fully. resolve_definition/get_span stay on jedi (they need real position
# resolution); only find_symbols moves here. References: services/spread/lsp.py (the SymbolMatch shape).

import ast
import os

from src.services.spread.lsp import SymbolMatch

# Directories we never scan -- deps, caches, VCS. A path with any of these components is skipped.
_SKIP_DIRS = frozenset({".venv", "venv", "site-packages", "__pycache__", ".git", "node_modules", ".mypy_cache",
                        ".pytest_cache", ".ruff_cache", "build", "dist"})


def _iter_py_files(root: str):
    """[Pure-ish] Yield absolute paths of .py files under `root`, pruning dependency/cache dirs. os.walk with
    in-place `dirs` pruning so we never descend into a skipped tree."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _scan_file(abs_path: str, root: str, name: str) -> list[SymbolMatch]:
    """[Pure-ish] Every def/async-def/class named `name` in one file, as SymbolMatch rows. A def directly
    inside a ClassDef is a Method (container = the class name); otherwise Function. class -> Class. Nested
    functions count too (jedi surfaced them). Unparseable file -> [] (skip, don't fail the whole scan)."""
    try:
        with open(abs_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    rel = os.path.relpath(abs_path, root)
    out: list[SymbolMatch] = []

    # Walk with parent tracking so we can tell a Method (def inside a class) from a Function. ast doesn't carry
    # parent links, so we thread the enclosing ClassDef name through an explicit stack.
    def _visit(node: ast.AST, class_stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name == name:
                    match: SymbolMatch = {
                        "symbol": child.name,
                        "path": rel,
                        "line": child.lineno,  # 1-based (ast is already 1-based for lineno)
                        "kind": "Method" if class_stack else "Function",
                    }
                    if class_stack:
                        match["container"] = class_stack[-1]
                    out.append(match)
                _visit(child, class_stack)  # descend: nested defs still count
            elif isinstance(child, ast.ClassDef):
                if child.name == name:
                    out.append({"symbol": child.name, "path": rel, "line": child.lineno, "kind": "Class"})
                _visit(child, class_stack + [child.name])
            else:
                _visit(child, class_stack)

    _visit(tree, [])
    return out


def find_symbols(root: str, name: str) -> list[SymbolMatch]:
    """[Pure-ish] All def/async-def/class definitions named EXACTLY `name` across the repo under `root`, as
    SymbolMatch rows (repo-root-relative paths, 1-based lines). Complete + deterministic (sorted by path then
    line) -- unlike jedi's partial workspace/symbol. Empty list = not found."""
    results: list[SymbolMatch] = []
    for abs_path in _iter_py_files(root):
        results.extend(_scan_file(abs_path, root, name))
    results.sort(key=lambda m: (m["path"], m["line"]))
    return results
