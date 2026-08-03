# Intentions: data access for subsystems -- large curated groupings with long-form markdown `content`.
# Project-scoped (project_id first). Owns endpoint_ids; flows are referenced inline in content (no
# flow_ids). References: docs/spec.md section 4.

from datetime import UTC, datetime

from src.dto import Subsystem
from src.repositories import COLL_SUBSYSTEMS
from src.utils import mongo


async def get(project_id: str, subsystem_id: str) -> Subsystem | None:
    return await mongo.find_one(COLL_SUBSYSTEMS, {"project_id": project_id, "id": subsystem_id})  # type: ignore[return-value]


async def find(project_id: str, query: dict) -> list[Subsystem]:
    return await mongo.find(COLL_SUBSYSTEMS, {"project_id": project_id, **query})  # type: ignore[return-value]


async def insert(subsystem: Subsystem) -> None:
    now = datetime.now(UTC)
    await mongo.insert_one(COLL_SUBSYSTEMS, {**subsystem, "created_at": now, "updated_at": now})


async def update(project_id: str, subsystem_id: str, updates: dict) -> None:
    await mongo.update_one(
        COLL_SUBSYSTEMS, {"project_id": project_id, "id": subsystem_id},
        {**updates, "updated_at": datetime.now(UTC)})


async def delete(project_id: str, subsystem_id: str) -> int:
    return await mongo.delete_one(COLL_SUBSYSTEMS, {"project_id": project_id, "id": subsystem_id})
