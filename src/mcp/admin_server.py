# Intentions: the MAINTAIN MCP (code-index-admin) -- the curation surface. Full CRUD for every entity plus
# the per-project commit-hash watermark and search-index rebuild. Controller layer: shape args into DTOs,
# call the curation service (which owns ref-validation + cascade), map errors. MULTI-PROJECT: every tool
# takes project_id; a project's root_path is seeded in the projects collection (server-side), so nothing to
# register -- rebuild_search_index looks it up. Startup ensures the compound indexes. Token-gated with its
# OWN token. References: docs/spec.md section 5.

from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from src.config import settings
from src.constants import CODE_INDEX_DESC, SEARCHABLE_ENTITY_TYPES, EntityType
from src.mcp.auth import BearerTokenMiddleware
from src.repositories import indexes
from src.services import curation, project_registry, search
from src.services.project_registry import ProjectRootMissing, UnknownProject
from src.utils import mongo

_INSTRUCTIONS = f"""
This mcp helps you curate and update the code index for the current project (current directory you're in). The code index is a to a codebase what an index is for a database table. It helps navigate and explore the codebase faster and with richer context. To do that well your job as a code index maintainer is paramount (although the human will help with curation where important as well).
{CODE_INDEX_DESC}
There will be a read MCP companion to this MCP for using the code index for the read path. It can filter those entities based on some parameters. Also there is the ability to "spread" and endpoint or a symbol to show the whole code content flattened recursively, for convenient viewing (using lsp). You can use this MCP too to aid with the editing process.

Before using the codebase you should read .codeindex.config.js to know which types of endpoints are there (e.g. REST handler, worker job handler), and the project id slug. The project id should be sent along in every tool request (check each tool's details) because the code index could be serving many projects at once.
You should also read the codebase's CLAUDE.md if available for more context on the codebase's info and conventions.

Your main tasks (aside from the specific ones asked by human) is to go through the codebase changes (obtained from git diff or git show etc, or initially from the whole codebase's content) and seed/update the code index accordingly. The steps:
- Use the read MCP to get all subsystems, logic artifacts and labels for context.
- Get the raw content change using git. You should get the current code index's last processed commit hash, then do a diff on that commit for the new changes (if there is no hash yet, it means the code index isn't seeded and you should consider the whole codebase for processing).
- From the changes, determine the updates/creations/deletions of the endpoints, and apply them (create_endpoint / update_endpoint / delete_endpoint). handler_location is `<path>:<symbol>` (the handler's def NAME, not a line number). update_endpoint takes any subset of fields -- on a rescan pass only the auto-scanned fields (kind/handler_location/trigger/last_scanned_commit) and OMIT the curated ones (description/annotation/labels/logic_artifacts) so you don't clobber human curation.
- From those updates in the endpoints, check if any flows need to be updated as well. Dont try to over update them though, lean on the lazy side. Update when there are genuinely new endpoints that should be added to any flow, or removing deleted endpoints from flows' lists, or update description/flow makeup if the new changes are really conflicting with the existing ones.
  - Actually the mcp will help with some consistency guards. E.g. when deleting an endpoint, and references to it (e.g. from flows) will be removed as well.
- Generate a report on what's been done, and recommend updates to subsystems, logic artifacts or labels. Again, for the recommendations, lean on the lazy side. Only suggest when there are genuine version conflicts or there's something really worth adding to the existing collections.
- Human will come in and review, curate and finalize the code index updates.
- Human will then instruct you to re-generate the vector index for semantic searching (this is quite mechanincal though).
- Update the commit hash. This will serve as the code index's watermark so we know how updated the code index is. Crucial for next update flow/edit process.
"""

server = MCPServer(name="code-index-admin", instructions=_INSTRUCTIONS)


def _err(exc: Exception) -> dict:
    # [Pure] uniform error envelope for the tools (dangling refs / conflicts / unknown project surface as
    # data, not crashes).
    return {"ok": False, "error": str(exc)}


# --- Endpoints ---

@server.tool(name="create_endpoint", description="Create an endpoint.")
async def create_endpoint(
    project_id: str,
    id: Annotated[str, Field(description="The endpoint id. Format is deterministic and follow .codeindex.config.js")],
    kind: Annotated[str, Field(description="Endpoint type. Of of the ones in .codeindex.config.js")],
    handler_location: Annotated[str, Field(description="<file/path/from/repo/root.ext>:<symbol> -- the "
                                "handler's file and def/function NAME (no line number; the line is resolved "
                                "live, so this stays stable when unrelated edits shift lines).")],
    trigger: Annotated[str, Field(description="E.g. `POST /api/v1/posts`, or worker name")],
    description: Annotated[str, Field(description="short description describing what it does, no more than 100 words. Can skip if the function is trivial or the name is descriptive enough")] = "",
    annotation: Annotated[str | None, Field(description="Any remarks, marginal notes or additional explicit comments. Most of the time this is not needed since the code should be explanatory enough. Totally fine to leave blank. To leave blank, dont provide this field instead of passing an empty string.")] = None,
    labels: Annotated[list[str] | None, Field(description="Label id slugs if any")] = None,
    logic_artifacts: Annotated[list[str] | None, Field(description="Associated logic artifact id slugs if any")] = None,
    last_scanned_commit: str = ""
) -> dict:
    try:
        new_id = await curation.create_endpoint({
            "project_id": project_id, "id": id, "kind": kind, "handler_location": handler_location,
            "trigger": trigger, "description": description, "annotation": annotation,
            "labels": labels or [], "logic_artifacts": logic_artifacts or [],
            "last_scanned_commit": last_scanned_commit})
        return {"ok": True, "id": new_id}
    except Exception as exc:  # noqa: BLE001 -- surface any write failure (dangling refs, conflicts) as data
        return _err(exc)


@server.tool(name="update_endpoint", description="Update an endpoint (any subset of its fields).")
async def update_endpoint(
    project_id: str,
    id: str,
    updates: Annotated[dict, Field(description="Fields to update (any subset). Updatable: kind, "
                                   "handler_location, trigger, last_scanned_commit, description, "
                                   "annotation, labels, logic_artifacts. See create_endpoint for each field's "
                                   "meaning. Unknown/protected keys (id, project_id) are ignored.")],
) -> dict:
    try:
        await curation.update_endpoint(project_id, id, updates)
        return {"ok": True, "id": id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="delete_endpoint", description="Delete an endpoint; cascade-purge it from flows/subsystems.")
async def delete_endpoint(project_id: str, id: str) -> dict:
    await curation.delete_endpoint(project_id, id)
    return {"ok": True, "id": id}


# --- Flows ---

@server.tool(name="create_flow", description="Create a flow. Rejects dangling endpoint/label/artifact refs.")
async def create_flow(
    project_id: str,
    id: str,
    description: Annotated[str, Field(description="Things that should be in here: what the flow does, sequential steps, any intentions or implications. For each, only put in if they deserve to be in. Dont make it bloated.")],
    endpoint_ids: Annotated[list[str], Field(description="List of endpoint ids involved")],
    labels: Annotated[list[str] | None, Field(description="Label id slugs if any")] = None,
    logic_artifacts: Annotated[list[str] | None, Field(description="Associated logic artifact id slugs if any")] = None,
    last_scanned_commit: str = "") -> dict:
    try:
        new_id = await curation.create_flow({
            "project_id": project_id, "id": id, "description": description, "endpoint_ids": endpoint_ids,
            "labels": labels or [], "logic_artifacts": logic_artifacts or [],
            "last_scanned_commit": last_scanned_commit})
        return {"ok": True, "id": new_id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="update_flow", description="Update a flow. Rejects dangling refs in the updated fields.")
async def update_flow(
    project_id: str,
    id: str,
    updates: Annotated[dict, Field(description="Fields to update (any subset). See create_flow for each field's meaning. Unknown/protected keys (id, project_id) are ignored.")],
) -> dict:
    try:
        await curation.update_flow(project_id, id, updates)
        return {"ok": True, "id": id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="delete_flow", description="Delete a flow.")
async def delete_flow(project_id: str, id: str) -> dict:
    await curation.delete_flow(project_id, id)
    return {"ok": True, "id": id}


# --- Subsystems ---

@server.tool(name="create_subsystem",
             description="Create a subsystem (endpoint/flow refs go inline in `content` markdown, no id "
                         "arrays). Rejects dangling label/artifact refs.")
async def create_subsystem(project_id: str, id: str, description: str, content: str = "",
                           labels: list[str] | None = None, logic_artifacts: list[str] | None = None,
                           last_scanned_commit: str = "") -> dict:
    try:
        new_id = await curation.create_subsystem({
            "project_id": project_id, "id": id, "description": description, "content": content,
            "labels": labels or [], "logic_artifacts": logic_artifacts or [],
            "last_scanned_commit": last_scanned_commit})
        return {"ok": True, "id": new_id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="update_subsystem", description="Update a subsystem. Rejects dangling refs.")
async def update_subsystem(project_id: str, id: str, updates: dict) -> dict:
    try:
        await curation.update_subsystem(project_id, id, updates)
        return {"ok": True, "id": id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="delete_subsystem", description="Delete a subsystem.")
async def delete_subsystem(project_id: str, id: str) -> dict:
    await curation.delete_subsystem(project_id, id)
    return {"ok": True, "id": id}


# --- Logic artifacts ---

@server.tool(name="create_logic_artifact", description="Create a logic artifact. Rejects dangling labels.")
async def create_logic_artifact(project_id: str, id: str, description: str,
                                labels: list[str] | None = None, last_scanned_commit: str = "") -> dict:
    try:
        new_id = await curation.create_logic_artifact({
            "project_id": project_id, "id": id, "description": description, "labels": labels or [],
            "last_scanned_commit": last_scanned_commit})
        return {"ok": True, "id": new_id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="update_logic_artifact", description="Update a logic artifact. Rejects dangling labels.")
async def update_logic_artifact(project_id: str, id: str, updates: dict) -> dict:
    try:
        await curation.update_logic_artifact(project_id, id, updates)
        return {"ok": True, "id": id}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="delete_logic_artifact",
             description="Delete a logic artifact; cascade-purge it from every entity's logic_artifacts.")
async def delete_logic_artifact(project_id: str, id: str) -> dict:
    await curation.delete_logic_artifact(project_id, id)
    return {"ok": True, "id": id}


# --- Labels ---

@server.tool(name="create_label", description="Create a label (controlled vocabulary; name is unique).")
async def create_label(project_id: str, name: str, description: str = "") -> dict:
    try:
        new_name = await curation.create_label(
            {"project_id": project_id, "name": name, "description": description})
        return {"ok": True, "name": new_name}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(name="update_label", description="Update a label's description.")
async def update_label(project_id: str, name: str, updates: dict) -> dict:
    await curation.update_label(project_id, name, updates)
    return {"ok": True, "name": name}


@server.tool(name="delete_label", description="Delete a label; cascade-purge it from every entity's labels.")
async def delete_label(project_id: str, name: str) -> dict:
    await curation.delete_label(project_id, name)
    return {"ok": True, "name": name}


# --- Per-project watermark ---

@server.tool(name="get_commit_hash", description="Read a project's index watermark (commit it reflects).")
async def get_commit_hash(project_id: str) -> dict:
    return {"commit_hash": await curation.get_commit_hash(project_id)}


@server.tool(name="set_commit_hash", description="Set a project's index watermark after a successful update flow.")
async def set_commit_hash(project_id: str, commit_hash: str) -> dict:
    await curation.set_commit_hash(project_id, commit_hash)
    return {"ok": True, "commit_hash": commit_hash}


# --- Semantic search index ---

@server.tool(name="rebuild_search_index",
             description="Rebuild a project's FAISS semantic-search vectors from its current entities. FULL "
                         "rebuild (re-embeds every entity; endpoints re-embed their live spread, so run AFTER "
                         "annotating). entity_types defaults to all searchable. Returns per-type counts.")
async def rebuild_search_index(project_id: str, entity_types: list[str] | None = None) -> dict:
    try:
        root_path = await project_registry.get_root(project_id)
    except (UnknownProject, ProjectRootMissing) as exc:
        return _err(exc)
    if entity_types is None:
        return {"ok": True, "indexed": await search.rebuild_all(project_id, root_path)}
    searchable = {t.value for t in SEARCHABLE_ENTITY_TYPES}
    unknown = [t for t in entity_types if t not in searchable]
    if unknown:
        return {"ok": False, "error": f"not searchable: {', '.join(unknown)}"}
    indexed = {t: await search.rebuild_index(project_id, root_path, EntityType(t)) for t in entity_types}
    return {"ok": True, "indexed": indexed}


def build_app():
    """The token-gated ASGI app. Ensures compound indexes on startup; uses the admin token. Resolvers are
    torn down on shutdown (resolvers are started lazily per-project from the DB root_path)."""
    app = server.streamable_http_app()
    inner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_):
        mongo.connect()
        await indexes.ensure_indexes()
        project_registry.install_shutdown_handlers()  # tear down resolvers on SIGTERM/SIGINT edge cases
        async with inner_lifespan(app_):
            yield
        await project_registry.stop_all()
        await mongo.close()

    app.router.lifespan_context = lifespan
    return BearerTokenMiddleware(app, settings.admin_mcp_token)
