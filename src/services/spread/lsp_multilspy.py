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

from multilspy import LanguageServer
from multilspy.multilspy_config import Language, MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

from src.services.spread import ast_symbols
from src.services.spread.lsp import Definition, Span, SymbolMatch


def _to_relative(file: str, root_path: str) -> str:
    # multilspy wants a repo-root-relative path; accept absolute or already-relative input.
    if os.path.isabs(file):
        return os.path.relpath(file, root_path)
    return file


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
        """All def/async-def/class definitions named EXACTLY `name` across the repo, via an AST scan (see
        ast_symbols) -- NOT jedi's workspace/symbol. Jedi's workspace/symbol is INCOMPLETE for common names:
        it returns only a small partial subset (for `update` it gave 3 of 6 defs, dropping every repo one),
        which silently broke `discover`. A name->sites lookup doesn't need the language server; an ast walk is
        complete + deterministic. The other resolver methods (resolve_definition/get_span) still use jedi,
        which needs real position resolution. [I/O: reads the repo's .py files]"""
        return ast_symbols.find_symbols(self._root, name)
