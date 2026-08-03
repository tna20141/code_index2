# Intentions: data access for flows -- curated groupings of endpoints. Project-scoped (project_id first).
# Owns endpoint_ids (the referencing side owns the reference). References: docs/spec.md section 4.

from datetime import UTC, datetime

from src.dto import Flow
from src.repositories import COLL_FLOWS
from src.utils import mongo


async def get(project_id: str, flow_id: str) -> Flow | None:
    return await mongo.find_one(COLL_FLOWS, {"project_id": project_id, "id": flow_id})  # type: ignore[return-value]


async def find(project_id: str, query: dict) -> list[Flow]:
    return await mongo.find(COLL_FLOWS, {"project_id": project_id, **query})  # type: ignore[return-value]


async def insert(flow: Flow) -> None:
    now = datetime.now(UTC)
    await mongo.insert_one(COLL_FLOWS, {**flow, "created_at": now, "updated_at": now})


async def update(project_id: str, flow_id: str, updates: dict) -> None:
    await mongo.update_one(
        COLL_FLOWS, {"project_id": project_id, "id": flow_id},
        {**updates, "updated_at": datetime.now(UTC)})


async def delete(project_id: str, flow_id: str) -> int:
    return await mongo.delete_one(COLL_FLOWS, {"project_id": project_id, "id": flow_id})
