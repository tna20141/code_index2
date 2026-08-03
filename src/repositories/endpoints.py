# Intentions: data access for endpoints -- the auto-generated entry points (HTTP route / kafka / periodic
# job / worker handler). All functions are project-scoped (project_id first param). `update` is unified:
# it writes any subset of the updatable fields the caller passes (whitelisted, so id/project_id/created_at
# can't be clobbered). References: docs/spec.md sections 4, 7.

from datetime import UTC, datetime

from src.dto import Endpoint
from src.repositories import COLL_ENDPOINTS
from src.utils import mongo

# Fields a caller may update (everything except id/project_id/created_at; updated_at is set here).
_UPDATABLE_FIELDS = ("kind", "handler_location", "signature", "trigger", "last_scanned_commit",
                     "description", "annotation", "labels", "logic_artifacts")


async def get(project_id: str, endpoint_id: str) -> Endpoint | None:
    return await mongo.find_one(COLL_ENDPOINTS, {"project_id": project_id, "id": endpoint_id})  # type: ignore[return-value]


async def find(project_id: str, query: dict) -> list[Endpoint]:
    return await mongo.find(COLL_ENDPOINTS, {"project_id": project_id, **query})  # type: ignore[return-value]


async def exists(project_id: str, endpoint_id: str) -> bool:
    return await mongo.find_one(
        COLL_ENDPOINTS, {"project_id": project_id, "id": endpoint_id}, {"id": 1}) is not None


async def find_missing(project_id: str, ids: list[str]) -> list[str]:
    """The subset of `ids` that don't exist IN THIS PROJECT -- for write-time reference validation."""
    present = {e["id"] for e in await mongo.find(
        COLL_ENDPOINTS, {"project_id": project_id, "id": {"$in": ids}}, {"id": 1})}
    return [i for i in ids if i not in present]


async def insert(endpoint: Endpoint) -> None:
    now = datetime.now(UTC)
    await mongo.insert_one(COLL_ENDPOINTS, {**endpoint, "created_at": now, "updated_at": now})


async def update(project_id: str, endpoint_id: str, updates: dict) -> None:
    """Update any subset of the updatable fields (whitelisted -- unknown/protected keys are ignored)."""
    fields = {k: updates[k] for k in _UPDATABLE_FIELDS if k in updates}
    fields["updated_at"] = datetime.now(UTC)
    await mongo.update_one(COLL_ENDPOINTS, {"project_id": project_id, "id": endpoint_id}, fields)


async def delete(project_id: str, endpoint_id: str) -> int:
    return await mongo.delete_one(COLL_ENDPOINTS, {"project_id": project_id, "id": endpoint_id})
