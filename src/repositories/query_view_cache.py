# Intentions: cache for repo-frontier inlined-query views. Non-entity: derived, project-scoped, keyed by
# (project_id, location, commit_sha). A miss (or sha mismatch) triggers regeneration. References:
# docs/spec.md sections 3, 4.

from datetime import UTC, datetime

from src.dto import QueryView
from src.repositories import COLL_QUERY_VIEW_CACHE
from src.utils import mongo


async def get(project_id: str, location: str, commit_sha: str) -> QueryView | None:
    """The cached view for this location AT this commit, in this project. A different sha reads as a miss."""
    return await mongo.find_one(  # type: ignore[return-value]
        COLL_QUERY_VIEW_CACHE,
        {"project_id": project_id, "location": location, "commit_sha": commit_sha})


async def upsert(view: QueryView) -> None:
    """Store/replace the view for its (project_id, location). Regeneration resets approved (caller passes it
    False)."""
    await mongo.update_one(
        COLL_QUERY_VIEW_CACHE,
        {"project_id": view["project_id"], "location": view["location"]},
        {**view, "generated_at": datetime.now(UTC)}, upsert=True)
