# Intentions: the ONLY contract spread depends on for code resolution -- a narrow Resolver protocol plus a
# factory. Any backend (pyright via multilspy, jedi, a custom client) implements this; swapping backends is
# swapping which impl the factory returns (config: RESOLVER_BACKEND). boundary.py / materialize.py depend on
# the resolver-agnostic Definition/Span DTOs below, never on the backend -- so the Node dependency (pyright)
# is quarantined to lsp_pyright.py. References: docs/spec.md section 2.

from typing import NotRequired, Protocol, TypedDict

from src.config import settings


class Definition(TypedDict):
    """Where a symbol at a call site is defined. Resolver-agnostic -- boundary.py does its realpath check on
    `path`, never touching the backend."""
    path: str   # absolute path of the defining file
    line: int   # 1-based
    col: int    # 1-based


class Span(TypedDict):
    """Full line range of a symbol's definition (the function body, decorators excluded -- materialize.py
    scans upward for those). 1-based, inclusive."""
    start_line: int
    end_line: int


class SymbolMatch(TypedDict):
    """A workspace-symbol hit -- minimal info for the discover tool / spread's multi-match disambiguation.
    `path` is repo-root-relative (no leading slash)."""
    symbol: str
    path: str
    line: int   # 1-based
    kind: str   # "Function" | "Class" | "Method" | ...
    container: NotRequired[str]  # the class name, for methods


class Resolver(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def resolve_definition(self, file: str, line: int, col: int) -> Definition | None:
        """The definition a call-site symbol at (file, line, col) points to. None = unresolved."""
        ...

    async def get_span(self, file: str, line: int, col: int) -> Span | None:
        """The full start..end line range of the definition at (file, line, col). None = not found."""
        ...

    async def find_symbols(self, name: str) -> list[SymbolMatch]:
        """Workspace-wide symbols matching `name` (used by discover + spread-by-symbol). Empty if none."""
        ...


def make_resolver(root_path: str) -> Resolver:
    """Construct a resolver bound to `root_path`, per settings.resolver_backend. The project registry owns
    one instance per project (no global singleton -- one server serves many codebases). Spread imports THIS,
    never a concrete backend -- so trying a different backend later is: add its impl, flip RESOLVER_BACKEND.

    "multilspy" (default) = multilspy-managed language server (jedi-language-server for Python: pip-only, no
    Node). "pyright"/"jedi" are accepted aliases -- pyright maps here too, since this multilspy build only
    ships jedi for Python; a dedicated pyright client would be a new branch."""
    if settings.resolver_backend in ("multilspy", "jedi", "pyright"):
        from src.services.spread.lsp_multilspy import MultilspyResolver
        return MultilspyResolver(root_path)
    raise ValueError(f"unknown resolver backend: {settings.resolver_backend}")
