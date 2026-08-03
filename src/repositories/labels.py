# Intentions: data access for labels -- the controlled vocabulary. Project-scoped (project_id first).
# Identified by `name` (unique within a project). References: docs/spec.md section 4.

from datetime import UTC, datetime

from src.dto import Label
from src.repositories import COLL_LABELS
from src.utils import mongo


async def get(project_id: str, name: str) -> Label | None:
    return await mongo.find_one(COLL_LABELS, {"project_id": project_id, "name": name})  # type: ignore[return-value]


async def find(project_id: str, query: dict) -> list[Label]:
    return await mongo.find(COLL_LABELS, {"project_id": project_id, **query})  # type: ignore[return-value]


async def find_missing(project_id: str, names: list[str]) -> list[str]:
    """The subset of `names` that don't exist IN THIS PROJECT -- for write-time reference validation."""
    present = {label["name"] for label in await mongo.find(
        COLL_LABELS, {"project_id": project_id, "name": {"$in": names}}, {"name": 1})}
    return [n for n in names if n not in present]


async def insert(label: Label) -> None:
    now = datetime.now(UTC)
    await mongo.insert_one(COLL_LABELS, {**label, "created_at": now, "updated_at": now})


async def update(project_id: str, name: str, updates: dict) -> None:
    await mongo.update_one(
        COLL_LABELS, {"project_id": project_id, "name": name},
        {**updates, "updated_at": datetime.now(UTC)})


async def delete(project_id: str, name: str) -> int:
    return await mongo.delete_one(COLL_LABELS, {"project_id": project_id, "name": name})
