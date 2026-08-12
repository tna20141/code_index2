# Intentions: standalone CLI to rebuild a project's FAISS semantic-search index locally, WITHOUT going through
# the MCP HTTP tool (whose client-side idle timeout aborts the endpoint rebuild -- embedding ~all endpoint
# spreads takes minutes). Same wiring the admin server's rebuild_search_index does: connect mongo, resolve the
# project's root_path, rebuild_all. Run it directly and let it finish; it prints per-type counts.
#
# Usage:
#   uv run python -m scripts.rebuild_index                 # default project (evolix-backend), all types
#   uv run python -m scripts.rebuild_index --project X     # a specific project
#   uv run python -m scripts.rebuild_index --types endpoint flow   # only some types
#
# References: src/mcp/admin_server.py:rebuild_search_index (the tool this mirrors); src/services/search.py.

import argparse
import asyncio
import logging
import time

from src.constants import SEARCHABLE_ENTITY_TYPES, EntityType
from src.services import project_registry, search
from src.utils import mongo


async def _run(project_id: str, types: list[str] | None) -> None:
    # Stream INFO logs (search._embed logs per batch) so the run isn't a silent black box -- the endpoint
    # phase folds a live spread per endpoint + embeds many batches, each a slow network round-trip.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")

    mongo.connect()  # motor connects lazily; db() asserts this was called
    root_path = await project_registry.get_root(project_id)  # raises if project/root missing
    print(f"rebuilding index for project={project_id!r} root_path={root_path}", flush=True)

    # Rebuild one type at a time (even the "all" case) so we print progress + a per-type timing/count as each
    # finishes -- rebuild_all is otherwise opaque until everything is done.
    entity_types = [EntityType(t) for t in types] if types else list(SEARCHABLE_ENTITY_TYPES)
    counts: dict[str, int] = {}
    total_started = time.monotonic()
    for et in entity_types:
        name = et.value
        print(f"[{name}] building + embedding...", flush=True)
        started = time.monotonic()
        n = await search.rebuild_index(project_id, root_path, et)
        counts[name] = n
        print(f"[{name}] indexed {n} in {time.monotonic() - started:.1f}s", flush=True)

    print(f"\ndone in {time.monotonic() - total_started:.1f}s. indexed per type:", flush=True)
    for t, n in counts.items():
        print(f"  {t:16} {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild a project's FAISS search index (local, no MCP).")
    parser.add_argument("--project", default="evolix-backend", help="project id/slug (default: evolix-backend)")
    parser.add_argument("--types", nargs="*", default=None,
                        help="entity types to rebuild (default: all searchable). e.g. --types endpoint flow")
    args = parser.parse_args()
    asyncio.run(_run(args.project, args.types))


if __name__ == "__main__":
    main()
