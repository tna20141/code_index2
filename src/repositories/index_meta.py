# Intentions: the per-project watermark -- the commit each project's index reflects. Base for that project's
# scan diff. One doc per project (keyed by project_id). References: docs/spec.md sections 4, 5, 7.

from datetime import UTC, datetime

from src.repositories import COLL_INDEX_META
from src.utils import mongo


async def get_commit_hash(project_id: str) -> str | None:
    doc = await mongo.find_one(COLL_INDEX_META, {"project_id": project_id})
    return doc["commit_hash"] if doc else None


async def set_commit_hash(project_id: str, commit_hash: str) -> None:
    await mongo.update_one(
        COLL_INDEX_META, {"project_id": project_id},
        {"project_id": project_id, "commit_hash": commit_hash, "updated_at": datetime.now(UTC)},
        upsert=True)
