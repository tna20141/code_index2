# Intentions: data access for projects -- the logical bucket per indexed codebase. Identified by `id` (slug);
# carries `root_path` (the source location ON THE SERVER). Seeded by hand (id + root_path); the read/admin
# sides only READ it here. References: docs/spec.md section 4 (multi-project).

from src.dto import Project
from src.repositories import COLL_PROJECTS
from src.utils import mongo


async def get(project_id: str) -> Project | None:
    return await mongo.find_one(COLL_PROJECTS, {"id": project_id})  # type: ignore[return-value]


async def find(query: dict) -> list[Project]:
    return await mongo.find(COLL_PROJECTS, query)  # type: ignore[return-value]
