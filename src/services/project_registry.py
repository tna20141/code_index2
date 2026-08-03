# Intentions: the LSP resolver registry -- one live resolver per project, keyed by project_id. The project's
# `root_path` is read from the DB (`projects.root_path`, seeded by hand -- the server is the single host of
# record for each codebase's source), NOT supplied by the client. So a read user needs no local clone and no
# handshake: they pass a project_id, and the resolver is started LAZILY on first use against the server's
# source. References: docs/spec.md (multi-project).

import asyncio
import os
import signal

from src.repositories import projects as projects_repo
from src.services.spread.lsp import Resolver, make_resolver


class UnknownProject(Exception):
    """No `projects` row for this project_id (or it has no root_path). Seed the project first (id + root_path
    in the projects collection)."""


class ProjectRootMissing(Exception):
    """The project's configured root_path doesn't exist on the server."""


_resolvers: dict[str, Resolver] = {}  # project_id -> its live LSP resolver (started lazily)


async def get_root(project_id: str) -> str:
    """The project's source root ON THE SERVER, from the DB. Raises UnknownProject if the project isn't
    seeded / has no root_path; ProjectRootMissing if the configured path doesn't exist."""
    project = await projects_repo.get(project_id)
    if project is None or not project.get("root_path"):
        raise UnknownProject(project_id)
    abs_root = os.path.realpath(project["root_path"])
    if not os.path.isdir(abs_root):
        raise ProjectRootMissing(f"{project_id}: root_path does not exist on server: {project['root_path']}")
    return abs_root


async def get_resolver(project_id: str) -> Resolver:
    """The project's live resolver, started LAZILY on first use (looks up root_path from the DB). Subsequent
    calls reuse the running one. Raises UnknownProject / ProjectRootMissing if the project isn't usable."""
    existing = _resolvers.get(project_id)
    if existing is not None:
        return existing
    root = await get_root(project_id)
    resolver = make_resolver(root)
    await resolver.start()  # pays the LSP indexing cost once, on first spread for this project
    _resolvers[project_id] = resolver
    return resolver


async def _stop_one(project_id: str) -> None:
    resolver = _resolvers.pop(project_id, None)
    if resolver is not None:
        await resolver.stop()


async def stop_all() -> None:
    """Tear down every resolver -- called on server shutdown. Idempotent (safe to call more than once)."""
    for project_id in list(_resolvers):
        await _stop_one(project_id)


def install_shutdown_handlers() -> None:
    """Belt-and-suspenders: on SIGTERM/SIGINT, schedule stop_all() so resolver subprocesses (jedi-language-
    server, spawned with start_new_session -> their own process group -> NOT killed with the parent's group)
    get torn down even on edge-case shutdowns. The normal graceful path already tears them down via the ASGI
    lifespan; this covers cases where that doesn't complete. Idempotent with the lifespan (stop_all is a
    no-op the second time). asyncio-level handlers coexist with uvicorn's own signal handling.
    NOTE: SIGKILL/OOM cannot be caught -- nothing runs, so a hard-killed process still orphans its resolvers
    until the next clean restart (see the startup-reaper TODO in docs/spec.md)."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(stop_all()))
        except (NotImplementedError, RuntimeError):
            pass  # e.g. non-main-thread or a platform without add_signal_handler -- lifespan still covers us
