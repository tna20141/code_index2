# Intentions: data access for logic artifacts -- named quirks/conventions/distinctive logic. Project-scoped
# (project_id first). Leaf vocabulary: carries labels but not logic_artifacts. References: docs/spec.md
# section 4.

from datetime import UTC, datetime

from src.dto import LogicArtifact
from src.repositories import COLL_LOGIC_ARTIFACTS
from src.utils import mongo


async def get(project_id: str, artifact_id: str) -> LogicArtifact | None:
    return await mongo.find_one(COLL_LOGIC_ARTIFACTS, {"project_id": project_id, "id": artifact_id})  # type: ignore[return-value]


async def find(project_id: str, query: dict) -> list[LogicArtifact]:
    return await mongo.find(COLL_LOGIC_ARTIFACTS, {"project_id": project_id, **query})  # type: ignore[return-value]


async def find_missing(project_id: str, ids: list[str]) -> list[str]:
    """The subset of `ids` that don't exist IN THIS PROJECT -- for write-time reference validation."""
    present = {a["id"] for a in await mongo.find(
        COLL_LOGIC_ARTIFACTS, {"project_id": project_id, "id": {"$in": ids}}, {"id": 1})}
    return [i for i in ids if i not in present]


async def insert(artifact: LogicArtifact) -> None:
    now = datetime.now(UTC)
    await mongo.insert_one(COLL_LOGIC_ARTIFACTS, {**artifact, "created_at": now, "updated_at": now})


async def update(project_id: str, artifact_id: str, updates: dict) -> None:
    await mongo.update_one(
        COLL_LOGIC_ARTIFACTS, {"project_id": project_id, "id": artifact_id},
        {**updates, "updated_at": datetime.now(UTC)})


async def delete(project_id: str, artifact_id: str) -> int:
    return await mongo.delete_one(COLL_LOGIC_ARTIFACTS, {"project_id": project_id, "id": artifact_id})
