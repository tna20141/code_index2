# Intentions: the multilspy-backed Resolver -- multilspy manages the language-server subprocess (no
# hand-rolled LSP protocol). For Python this multilspy build ships jedi-language-server (pip-only, no Node),
# which resolves definitions/spans for a well-typed FastAPI codebase like evolix perfectly well. This is the
# ONLY file that knows multilspy exists; swapping to a different backend (a real pyright client) is a new
# file + flipping RESOLVER_BACKEND, with spread untouched (the Resolver seam in lsp.py).
#
# multilspy specifics we adapt to: 0-based line/column (LSP) vs our 1-based; repo-root-RELATIVE paths; a
# start_server() ASYNC context we hold open for the resolver's lifetime (indexing is the expensive part --
# pay it once); and open_file(), which is a SYNC context manager. References: docs/spec.md section 2.

import os
from urllib.parse import unquote, urlparse

from multilspy import LanguageServer
from multilspy.multilspy_config import Language, MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from multilspy.multilspy_types import SymbolKind

from src.services.spread.lsp import Definition, Span, SymbolMatch


def _to_relative(file: str, root_path: str) -> str:
    # multilspy wants a repo-root-relative path; accept absolute or already-relative input.
    if os.path.isabs(file):
        return os.path.relpath(file, root_path)
    return file


def _symbol_kind_name(kind) -> str:
    # [Pure] LSP SymbolKind (an int enum) -> its name ("Function"/"Class"/"Method"/...). Robust to int input.
    try:
        return SymbolKind(kind).name
    except (ValueError, KeyError):
        return str(kind)


def _uri_to_path(uri: str) -> str:
    # [Pure] a file:// URI -> a plain filesystem path (LSP Locations carry uri, not a bare path).
    if not uri:
        return ""
    parsed = urlparse(uri)
    return unquote(parsed.path) if parsed.scheme == "file" else uri


class MultilspyResolver:
    """Resolver backed by multilspy (jedi-language-server for Python), bound to one `root_path`. Holds the
    server context open for its lifetime. The project registry owns one instance per project."""

    def __init__(self, root_path: str) -> None:
        self._root = root_path
        self._server: LanguageServer | None = None
        self._ctx = None  # the live start_server() async context

    async def start(self) -> None:
        if self._server is not None:
            return
        config = MultilspyConfig(code_language=Language.PYTHON)
        server = LanguageServer.create(config, MultilspyLogger(), self._root)
        self._ctx = server.start_server()
        self._server = await self._ctx.__aenter__()

    async def stop(self) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
        self._server = None
        self._ctx = None

    def _require(self) -> LanguageServer:
        assert self._server is not None, "resolver not started; call start() first"
        return self._server

    async def resolve_definition(self, file: str, line: int, col: int) -> Definition | None:
        """(line, col) are 1-based (our convention); multilspy is 0-based -- shift. Returns the FIRST location
        (a call site resolves to one definition; overloads are rare in evolix). open_file is a SYNC context."""
        server = self._require()
        rel = _to_relative(file, self._root)
        try:
            with server.open_file(rel):
                locations = await server.request_definition(rel, line - 1, col - 1)
        except AssertionError:
            # multilspy asserts on a None LSP response (symbol not resolvable at this position) instead of
            # returning []. Treat as unresolved -> spread's branch 1 (leaf, leave the call line as-is).
            return None
        if not locations:
            return None
        loc = locations[0]
        start = loc["range"]["start"]
        return Definition(path=loc["absolutePath"], line=start["line"] + 1, col=start["character"] + 1)

    async def get_span(self, file: str, line: int, col: int) -> Span | None:
        """Full definition span via document symbols: the innermost symbol whose range contains `line`.
        multilspy 0-based -> our 1-based on the way out. `col` is unused (line containment suffices)."""
        server = self._require()
        rel = _to_relative(file, self._root)
        with server.open_file(rel):
            symbols, _ = await server.request_document_symbols(rel)
        target = line - 1  # to 0-based for comparison
        containing = [
            s for s in symbols
            if "range" in s and s["range"]["start"]["line"] <= target <= s["range"]["end"]["line"]
        ]
        if not containing:
            return None
        # innermost (smallest span) wins -- a method inside a class matches both; we want the method.
        best = min(containing, key=lambda s: s["range"]["end"]["line"] - s["range"]["start"]["line"])
        return Span(start_line=best["range"]["start"]["line"] + 1,
                    end_line=best["range"]["end"]["line"] + 1)

    async def find_symbols(self, name: str) -> list[SymbolMatch]:
        """workspace/symbol for `name` -> def-like matches (Function/Class/Method), paths repo-relative.
        workspace/symbol is FUZZY, so we keep only EXACT-name matches (discover means 'locate this symbol',
        not 'symbols starting with'). Filters to symbols DEFINED IN this repo (workspace-symbol can surface
        library symbols too). The LSP Location carries `uri` (a file:// URI) + `range` at its top level."""
        server = self._require()
        symbols = await server.request_workspace_symbol(name)
        matches: list[SymbolMatch] = []
        for s in symbols or []:
            if s.get("name") != name:
                continue  # workspace/symbol is fuzzy -- drop prefix/substring hits, keep exact name only
            kind = _symbol_kind_name(s.get("kind"))
            if kind not in ("Function", "Class", "Method"):
                continue
            loc = s.get("location") or {}
            abs_path = _uri_to_path(loc.get("uri", ""))
            if not abs_path or not os.path.realpath(abs_path).startswith(os.path.realpath(self._root)):
                continue  # skip symbols outside this repo (stdlib/site-packages)
            start = (loc.get("range") or {}).get("start", {})
            match: SymbolMatch = {
                "symbol": s["name"],
                "path": os.path.relpath(abs_path, self._root),
                "line": start.get("line", 0) + 1,
                "kind": kind,
            }
            if s.get("containerName"):
                match["container"] = s["containerName"]
            matches.append(match)
        return matches
