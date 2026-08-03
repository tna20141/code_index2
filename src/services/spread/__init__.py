# services/spread: THE read path's crown jewel -- given an endpoint (or any function), inline its whole call
# chain into one reading-only stitched-source artifact. This __init__ is the module's PUBLIC FACADE: callers
# import `spread` from here; the internals (lsp / boundary / materialize / render / query_view) are sealed.
#
# Traversal: DFS from the start function's body. At each call site we resolve the callee and classify it
# (boundary.py) into exactly one of the branches below (disjoint & exhaustive on the callee's resolution):
#   1. unresolved             -> leaf, leave the call line as-is
#   2. library boundary       -> leaf, leave as-is
#   3. trivial (# ci:trivial)  -> leaf, leave as-is
#   4. repo-frontier          -> leaf; emit body + inlined query view (query_view.py)
#   5. ordinary own-code      -> DESCEND: spread-begin -> recurse -> spread-end
#   6. max_depth reached      -> stop (leaf), regardless of class
#   7. cycle (on the stack)   -> stop, leave as-is (prevents infinite recursion)
#
# Call sites are found with `ast` over the callee's body span (Call nodes -> the callee-name token's
# line/col, which the resolver maps to a definition). The spec's leaves emit NO marker -- only descended
# callees get the begin/end pair. References: docs/spec.md section 2.

import ast
import os
import textwrap
from dataclasses import dataclass

from src.constants import SpreadMode
from src.services.spread import boundary, materialize, query_view, render
from src.services.spread.lsp import Definition, Resolver

__all__ = ["spread"]


@dataclass(frozen=True)
class _Ctx:
    """The per-spread context threaded through the traversal -- everything project-specific in one place
    (root_path/resolver come from the project registry; the caller passes project_id for the query-view
    cache). Keeps _spread_node's signature to (ctx, definition, depth, stack)."""
    project_id: str
    root_path: str
    resolver: Resolver
    mode: SpreadMode
    max_depth: int | None


def _rel(path: str, root_path: str) -> str:
    # [Pure] path-from-repo-root, for markers and cache keys.
    return os.path.relpath(path, root_path) if os.path.isabs(path) else path


def _leading_ws(line: str) -> str:
    # [Pure] the leading-whitespace prefix of a line (for indented-mode child padding).
    return line[:len(line) - len(line.lstrip())]


def _call_sites(body_lines: list[str], base_line: int) -> list[tuple[int, int, str]]:
    """[Pure] (abs_line, abs_col, name) for each call site in `body_lines` (1-based file line `base_line` is
    the block's first line). Parse the dedented block with `ast`; the token to resolve is the rightmost name
    of the Call's func (foo() -> foo; a.b.c() -> c). Absolute column is recovered by locating the token on the
    real (non-dedented) source line, which sidesteps dedent-offset bookkeeping."""
    if not body_lines:
        return []
    dedented = textwrap.dedent("\n".join(body_lines))
    try:
        tree = ast.parse(dedented)
    except SyntaxError:
        return []  # a non-parseable fragment (rare) yields no descent -- safe
    sites: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name, rel_line = func.id, func.lineno
        elif isinstance(func, ast.Attribute):
            name, rel_line = func.attr, (func.end_lineno or func.lineno)
        else:
            continue
        idx = rel_line - 1  # 0-based into body_lines
        if idx >= len(body_lines):
            continue
        col = body_lines[idx].find(name)
        if col == -1:
            continue
        sites.append((base_line + idx, col + 1, name))  # 1-based line & col in the file
    return sites


async def _spread_node(ctx: _Ctx, definition: Definition, depth: int,
                       stack: frozenset[str], symbol: str = "") -> list[str]:
    """Materialize one definition and (if ordinary own-code) recursively spread its call sites. Returns the
    rendered block lines (leading comments + body, with descended callees injected). `stack` holds the ref of
    every definition currently being spread (cycle guard). `symbol` is the callee name from the CALL SITE that
    reached this node (empty for the root -- it has no call site); passed to query_view as its anchor."""
    path, def_line = definition["path"], definition["line"]
    ref = f"{_rel(path, ctx.root_path)}:{def_line}"

    span = await ctx.resolver.get_span(path, def_line, definition["col"])
    if span is None:
        return []  # can't locate the body -> nothing to emit
    leading = materialize.read_leading(path, def_line)
    body = materialize.read_body(path, span)

    # Branch 4 -- repo-frontier: leaf, enriched with the inlined query view (still emits the body's meaning).
    if boundary.is_repo_frontier(definition):
        view = await query_view.get_or_generate(
            ctx.project_id, ctx.root_path, ref, "\n".join(body), symbol=symbol)
        return leading + view.splitlines()

    # Branch 6 (depth cap) / 7 (cycle): emit the body, don't descend.
    if (ctx.max_depth is not None and depth >= ctx.max_depth) or ref in stack:
        return leading + body

    stack = stack | {ref}
    sites_by_line: dict[int, list[tuple[int, str]]] = {}   # file_line -> [(col, callee_name), ...]
    for line, col, name in _call_sites(body, span["start_line"]):
        sites_by_line.setdefault(line, []).append((col, name))

    out: list[str] = []
    for offset, line_text in enumerate(body):
        out.append(line_text)
        file_line = span["start_line"] + offset
        for col, name in sites_by_line.get(file_line, []):
            child = await ctx.resolver.resolve_definition(path, file_line, col)
            if child is None:                                 # branch 1: unresolved
                continue
            if boundary.is_library_call(child, ctx.root_path):  # branch 2: library
                continue
            child_leading = materialize.read_leading(child["path"], child["line"])
            if boundary.is_trivial(child_leading):            # branch 3: trivial
                continue
            child_ref = f"{_rel(child['path'], ctx.root_path)}:{child['line']}"  # branch 4/5: descend
            child_block = await _spread_node(ctx, child, depth + 1, stack, symbol=name)
            if child_block:
                child_indent = _leading_ws(line_text) + "    "
                out += render.wrap(child_ref, child_block, ctx.mode, child_indent)
    return leading + out


async def spread(project_id: str, root_path: str, resolver: Resolver, target: Definition,
                 mode: SpreadMode = SpreadMode.INDENTED, max_depth: int | None = None) -> str:
    """Spread `target` (a resolved start definition) into the stitched-source artifact, for `project_id`
    (root_path + resolver come from the project registry). The caller resolves an endpoint id / `path:func`
    to a Definition first (the read MCP does this). Returns the joined text."""
    ctx = _Ctx(project_id=project_id, root_path=root_path, resolver=resolver, mode=mode, max_depth=max_depth)
    block = await _spread_node(ctx, target, depth=0, stack=frozenset())
    return "\n".join(block)
