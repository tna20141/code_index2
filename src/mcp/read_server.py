# Intentions: the READ MCP (code-index) -- the navigation surface. Three tools: spread / list / search.
# Controller layer: parse tool args, call a service, shape the response. No business logic here (it lives in
# services/spread, services/reads, services/search). Startup wiring (Mongo + resolver) and token gating are
# applied by build_app(). References: docs/spec.md section 5.

from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from src.config import settings
from src.constants import CODE_INDEX_DESC, SpreadMode
from src.mcp.auth import BearerTokenMiddleware
from src.services import documents, project_registry, reads, search
from src.services import spread as spread_svc
from src.services.documents import DocumentAccessError, NoDocumentsConfigured
from src.services.project_registry import ProjectRootMissing, UnknownProject
from src.utils import mongo


def _project_error(exc: Exception) -> str:
    # a UnknownProject / ProjectRootMissing -> a user-facing message (project not usable).
    if isinstance(exc, UnknownProject):
        return f"unknown project '{exc}': seed it (id + root_path) in the projects collection first"
    return str(exc)  # ProjectRootMissing already carries a full message

_INSTRUCTIONS = f"""
This mcp helps you use the code index to explore and navigate the codebase for a project.
{CODE_INDEX_DESC}
The project id (slug) is given to you; send it along in every tool request (check each tool's details) because the code index could be serving many projects at once.

It's best to get all subsystems, logic artifacts and labels for context, before you attempt to answer queries.

The project may also expose curated REFERENCE DOCUMENTS (architecture notes, ADRs, domain docs). Call `list_documents` to see what's available (each has a description of what it is and when to fetch); `read_documents` to read files/folders verbatim; `list_directory` to browse a doc folder. Consult these when a query needs design rationale or domain context the code alone doesn't give.

If you need to inspect the actual code (which you often do), use the spread tool to get an endpoint or a symbol's full content flatten, for a complete view of the logic throughout the call chain.
- The spread will skip dynamic invocation .e.g. functions as params, or function names as string (since the spread is only done statically). You're free to go from there to explore the codebase even further (you usually won't have the codebase ready so you can inspect yourself, so you can ask the mcp to inspect/spread a particular node/symbol).
- Sometimes you have access to the codebase's actual source though. If so you can make use of that if you want, but the code index should be consulted first since it's already arranged in a way to make exploration easier.

Now, the human could be a technical person (a dev), or a non-tech person (e.g. a business person or PO). A non-tech person probably just wants to know the current behavior of the system, from a business standpoint (even if it could get into details sometimes). A tech person on the other hand should want to know the code and the techincal details, and could actually be an llm agent doing development work. Tailor your answers accordingly.
- Be default, assume it's a tech person. If during the conversation, you suspect they may be non-tech, you can ask them if they are and adapt your answer style. You maybe the person can tell you themselves beforehand.

- Finally, be sure to check out CLAUDE.md if available in the codebase you're in. It may contain clues on the specific project/codebase, plus how you can use additional tools to aid with inspecting the codebase. Usually there might be helpful mcps as well so be sure to check that.
"""

server = MCPServer(name="code-index", instructions=_INSTRUCTIONS)


@server.tool(name="list_projects",
             description="List the indexed codebases (project slugs) available on this server. Pass one as "
                         "`project_id` to the other tools.")
async def list_projects() -> list[dict]:
    return [{"id": p["id"]} for p in await reads.list_projects()]


@server.tool(
    name="get_project_info",
    description=(
        "Get a project's info record. Shape:\n"
        "  id           : the project slug (pass as project_id to other tools).\n"
        "  root_path    : the codebase's source path on the server.\n"
        "  endpoint_types: the KINDS of endpoints in this codebase -- [{kind, description, paths}]. `kind` is "
        "the type name (e.g. http, kafka, periodic_job); `description` explains what that trigger family is; "
        "`paths` are the folders it lives in. (This is how you learn what an endpoint's `kind` means.)\n"
        "  documents    : curated reference docs exposed for reading -- [{path, description}]; each `path` is "
        "a file or a directory (trailing '/'), `description` says what it is and when to fetch. Read them "
        "with `read_documents` / browse with `list_directory`.\n"
        "Good to call up front for orientation on a project.")
)
async def get_project_info_tool(project_id: str) -> dict:
    info = await reads.get_project_info(project_id)
    if info is None:
        return {"error": f"unknown project: {project_id}"}
    return info


@server.tool(
    name="discover",
    description="Locate a symbol (function/class/method) across the codebase. Give `symbol` (bare name) to "
                "search the whole repo, or add `path` (full path-from-repo-root, e.g. "
                "'src/services/campaigns.py') to scope to one file. Returns a list of matches, each "
                "{symbol, path, line, kind, container?} -- use one to build a spread target. Empty list = "
                "not found.")
async def discover_tool(project_id: str, symbol: str, path: str | None = None) -> list[dict]:
    try:
        resolver = await project_registry.get_resolver(project_id)
    except (UnknownProject, ProjectRootMissing) as exc:
        return [{"error": _project_error(exc)}]
    return await reads.discover_symbols(resolver, symbol, path)


@server.tool(
    name="spread",
    description=(
        "Spread an endpoint or function into its inlined call-chain reading view: the whole flow stitched "
        "into one text, with `# && spread-begin:/spread-end:` markers around each descended callee (rely on "
        "those markers for structure, not indentation).\n"
        "Each node when spread will be inserted almost verbatim into the output (with inner and preceding comments), "
        "although sometimes the code index editor could inline or rewrite the content a bit to be easier to consume. "
        "The call chain is traversed and spread recursively, stopping either at library boundary or trivial nodes (marked by `# ci:trivial`). "
        "If you ever want to inspect a trivial node, specify that node directly by providing the symbol name "
        "(note that its descendants would still follow the rule).\n"
        "\n"
        "Specify the target with EXACTLY ONE of these (precedence high->low if several are given):\n"
        "  - endpoint_id : an endpoint's id -> spreads its handler.\n"
        "  - location    : a 'path-from-repo-root:lineno' (e.g. 'src/services/foo.py:142').\n"
        "  - symbol      : a function/class/method NAME; add `path` (full path-from-repo-root) to scope it. "
        "If the symbol resolves to MORE THAN ONE location, spread does NOT run -- it returns the list of "
        "matches with a warning so you can disambiguate (pass `path`, or use `location`).\n"
        "\n"
        "mode: 'indented' (default) or 'flat'. max_depth caps recursion.")
)
async def spread_tool(project_id: str, endpoint_id: str | None = None, location: str | None = None,
                      symbol: str | None = None, path: str | None = None,
                      mode: str = "indented", max_depth: int | None = None) -> dict:
    try:
        root_path = await project_registry.get_root(project_id)
        resolver = await project_registry.get_resolver(project_id)
    except (UnknownProject, ProjectRootMissing) as exc:
        return {"error": _project_error(exc)}

    # Resolve the start Definition by precedence: endpoint_id > location > symbol.
    if endpoint_id is not None:
        definition, err = await reads.resolve_endpoint_start(resolver, project_id, root_path, endpoint_id)
        if err is not None:
            return {"error": err}
    elif location is not None:
        definition = reads.resolve_location_start(root_path, location)
        if definition is None:
            return {"error": f"malformed location (want 'path:lineno'): {location}"}
    elif symbol is not None:
        matches = await reads.discover_symbols(resolver, symbol, path)
        if not matches:
            return {"error": f"symbol not found: {symbol}"}
        if len(matches) > 1:
            return {"warning": f"'{symbol}' has {len(matches)} matches; disambiguate with `path` or use "
                               "`location`.", "matches": matches}
        definition = reads.match_to_definition(root_path, matches[0])
    else:
        return {"error": "specify one of: endpoint_id, location, or symbol"}

    content = await spread_svc.spread(
        project_id, root_path, resolver, definition, mode=SpreadMode(mode), max_depth=max_depth)
    return {"content": content}


@server.tool(name="list",
             description="List entities of a type (endpoint|flow|subsystem|logic_artifact|label) with "
                         "AND-combined filters (ids, labels, logic_artifacts, kind) and optional field "
                         "projection (select). Pass ids to fetch specific entities. To read an endpoint's "
                         "call chain, use the `spread` tool.\n"
                         "Use `select` to tell the mcp to only return the fields you want."
             )
async def list_tool(project_id: str, entity_type: str, ids: list[str] | None = None,
                    labels: list[str] | None = None, logic_artifacts: list[str] | None = None,
                    kind: str | None = None, select: list[str] | None = None) -> list[dict]:
    return await reads.list_entities(project_id, entity_type, ids, labels, logic_artifacts, kind, select)


@server.tool(name="search",
             description="Semantic search over a project's entities. Returns ranked [{id, entity_type, "
                         "score}] (lower score = closer). entity_types defaults to all searchable types.")
async def search_tool(project_id: str, query: str, entity_types: list[str] | None = None,
                      top_k: int = 20) -> list[dict]:
    return await search.search(project_id, query, entity_types, top_k)


# --- Project documents (curated verbatim reference files/folders; allowlist-gated) ---

@server.tool(name="list_documents",
             description="List the project's curated reference documents -- [{path, description}]. Each is a "
                         "file or a directory (trailing '/') the project has exposed, with a note on what it "
                         "is and when to fetch. Use `read_documents` to read them, `list_directory` to browse "
                         "a directory. Empty if none configured.")
async def list_documents_tool(project_id: str) -> list[dict]:
    return await documents.list_documents(project_id)


@server.tool(name="read_documents",
             description="Read one or more of the project's allowed documents verbatim. `paths` may mix files "
                         "and directories (repo-root-relative). A directory is read RECURSIVELY (all files "
                         "under it). Only allowlisted paths are permitted -- if ANY path is disallowed the "
                         "whole call fails. Returns one text with each file marked `===== FILE: <path> =====`.")
async def read_documents_tool(project_id: str, paths: list[str]) -> dict:
    try:
        return {"content": await documents.read_documents(project_id, paths)}
    except (DocumentAccessError, NoDocumentsConfigured) as exc:
        return {"error": str(exc)}


@server.tool(name="list_directory",
             description="List the immediate (non-recursive) contents of an allowed document directory -- "
                         "[{name, path, type: 'file'|'dir'}]. Subdirs can be listed further; files read via "
                         "read_documents. The directory must be within the project's document allowlist.")
async def list_directory_tool(project_id: str, path: str) -> dict:
    try:
        return {"entries": await documents.list_directory(project_id, path)}
    except (DocumentAccessError, NoDocumentsConfigured) as exc:
        return {"error": str(exc)}


def build_app():
    """The token-gated ASGI app. Wraps the MCP app's lifespan so Mongo connects and the resolver starts
    before serving (and the resolver stops on shutdown)."""
    app = server.streamable_http_app()
    inner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_):
        # Connect Mongo eagerly (cheap). The resolver is started LAZILY on the first spread -- starting it
        # here would block the ASGI lifespan on the LSP initialize handshake and delay the server booting.
        mongo.connect()
        project_registry.install_shutdown_handlers()  # tear down resolvers on SIGTERM/SIGINT edge cases
        async with inner_lifespan(app_):
            yield
        await project_registry.stop_all()
        await mongo.close()

    app.router.lifespan_context = lifespan
    return BearerTokenMiddleware(app, settings.read_mcp_token)
