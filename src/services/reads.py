# Intentions: the read-side query surface behind the read MCP's `list` tool -- fetch entities by type with
# AND-combined filters (ids, labels, logic_artifacts, kind), plus field projection. Also resolves an endpoint
# id / "path:lineno" target into a start Definition for the spread tool. References: docs/spec.md sections 4, 5.

import os

from src.constants import EntityType
from src.repositories import endpoints as endpoints_repo
from src.repositories import flows as flows_repo
from src.repositories import labels as labels_repo
from src.repositories import logic_artifacts as logic_artifacts_repo
from src.repositories import projects as projects_repo
from src.repositories import subsystems as subsystems_repo
from src.services.spread.lsp import Definition, Resolver, SymbolMatch

# module-aliased imports so the `labels` / `logic_artifacts` FILTER PARAMS below don't shadow the repos.
_REPOS = {
    EntityType.ENDPOINT: endpoints_repo,
    EntityType.FLOW: flows_repo,
    EntityType.SUBSYSTEM: subsystems_repo,
    EntityType.LOGIC_ARTIFACT: logic_artifacts_repo,
    EntityType.LABEL: labels_repo,
}


def _build_query(entity_type: str, ids: list[str] | None, label_names: list[str] | None,
                 artifact_ids: list[str] | None, kind: str | None) -> dict:
    """[Pure] AND-combine the filters into a Mongo query. `ids` matches the entity's business key
    (labels: name; others: id). Array filters use $all (must contain ALL requested)."""
    query: dict = {}
    key = "name" if entity_type == EntityType.LABEL else "id"
    if ids:
        query[key] = {"$in": ids}
    if label_names:
        query["labels"] = {"$all": label_names}
    if artifact_ids:
        query["logic_artifacts"] = {"$all": artifact_ids}
    if kind:
        query["kind"] = kind
    return query


def _project(docs: list[dict], select: list[str] | None) -> list[dict]:
    # [Pure] keep only `select` fields (if given). Done in-app so it composes with the strip-_id repos.
    if not select:
        return docs
    return [{k: d.get(k) for k in select} for d in docs]


async def list_projects() -> list[dict]:
    """All indexed projects (their slugs) available on this server."""
    return await projects_repo.find({})


async def list_entities(project_id: str, entity_type: str, ids: list[str] | None = None,
                        labels: list[str] | None = None, logic_artifacts: list[str] | None = None,
                        kind: str | None = None, select: list[str] | None = None) -> list[dict]:
    """List `entity_type` entities in `project_id` matching all filters; also the getter (pass `ids`)."""
    repo = _REPOS[EntityType(entity_type)]
    query = _build_query(entity_type, ids, labels, logic_artifacts, kind)
    return _project(await repo.find(project_id, query), select)


def _strip_slash(path: str) -> str:
    # [Pure] drop a single leading slash so repo-relative paths normalize to no-leading-slash (the convention
    # used by spread markers + path:lineno). Inputs here are always repo-relative, never true abs paths.
    return path.removeprefix("/")


def _location_definition(root_path: str, location: str) -> Definition | None:
    # [Pure] "path:lineno" (repo-relative, optional leading slash) -> a start Definition. None if malformed.
    path, _, lineno = location.rpartition(":")
    if not lineno.isdigit():
        return None
    path = _strip_slash(path)
    abs_path = path if os.path.isabs(path) else os.path.join(root_path, path)
    return Definition(path=abs_path, line=int(lineno), col=1)


async def discover_symbols(resolver: Resolver, symbol: str,
                           path: str | None = None) -> list[SymbolMatch]:
    """Find workspace symbols named `symbol` (def-like), optionally scoped to `path` (full path-from-repo-root
    e.g. 'src/a/b.py'; leading slash tolerated). Returns minimal-info matches; empty if none."""
    matches = await resolver.find_symbols(symbol)
    if path:
        want = _strip_slash(path)
        matches = [m for m in matches if m["path"] == want]
    return matches


async def resolve_endpoint_start(resolver: Resolver, project_id: str, root_path: str,
                                 endpoint_id: str) -> tuple[Definition | None, str | None]:
    """An endpoint id -> (start Definition, error). handler_location is "{path}:{symbol}" (no line number,
    for stability), so we resolve the symbol to its CURRENT line via LSP. Returns (def, None) on success, or
    (None, error) if the endpoint is missing / handler_location is malformed / the symbol can't be uniquely
    located in that file (moved, renamed, or ambiguous)."""
    ep = await endpoints_repo.get(project_id, endpoint_id)
    if ep is None:
        return None, f"endpoint not found: {endpoint_id}"
    path, _, symbol = ep["handler_location"].rpartition(":")
    if not path or not symbol:
        return None, f"malformed handler_location (want 'path:symbol'): {ep['handler_location']}"
    matches = await discover_symbols(resolver, symbol, _strip_slash(path))
    if not matches:
        return None, f"handler '{symbol}' not found in {path} (moved/renamed? re-scan the endpoint)"
    if len(matches) > 1:
        return None, f"handler '{symbol}' is ambiguous in {path} ({len(matches)} matches)"
    return match_to_definition(root_path, matches[0]), None


def resolve_location_start(root_path: str, location: str) -> Definition | None:
    """A raw "path:lineno" target -> a start Definition (public wrapper over _location_definition)."""
    return _location_definition(root_path, location)


def match_to_definition(root_path: str, match: SymbolMatch) -> Definition:
    # [Pure] a resolved SymbolMatch -> the start Definition to spread from.
    return Definition(path=os.path.join(root_path, match["path"]), line=match["line"], col=1)
