# Intentions: ensure the unique indexes the storage model relies on (docs/spec.md section 4). Run once at
# admin-MCP startup. MULTI-PROJECT: entity uniqueness is COMPOUND {project_id, key} -- two projects may share
# an id/name. projects.id is globally unique (the slug is the project identity).

import pymongo

from src.repositories import (
    COLL_ENDPOINTS,
    COLL_FLOWS,
    COLL_INDEX_META,
    COLL_LABELS,
    COLL_LOGIC_ARTIFACTS,
    COLL_PROJECTS,
    COLL_QUERY_VIEW_CACHE,
    COLL_SUBSYSTEMS,
)
from src.utils import mongo

# Obsolete single-field indexes from the PRE-multi-project schema (uniqueness was global, not per-project).
# They are WRONG now -- a single-field unique on `id`/`name`/`location` blocks two projects from sharing a
# key, and `_meta_1` (a removed field) lets only one project have an index_meta row. Dropped on startup so a
# restore from an older dump (which carries these) self-heals. {collection: [stale index names]}.
_STALE_INDEXES = {
    COLL_ENDPOINTS: ["id_1"],
    COLL_FLOWS: ["id_1"],
    COLL_SUBSYSTEMS: ["id_1"],
    COLL_LOGIC_ARTIFACTS: ["id_1"],
    COLL_LABELS: ["name_1"],
    COLL_QUERY_VIEW_CACHE: ["location_1"],
    COLL_INDEX_META: ["_meta_1"],
}


async def _drop_stale_indexes() -> None:
    for coll, names in _STALE_INDEXES.items():
        for name in names:
            try:
                await mongo.collection(coll).drop_index(name)
            except Exception:  # noqa: BLE001, S110 -- index absent (already clean / fresh DB) is fine
                pass


async def ensure_indexes() -> None:
    await _drop_stale_indexes()  # remove pre-multi-project single-field uniques before creating the right ones
    await mongo.collection(COLL_PROJECTS).create_index("id", unique=True)
    for coll in (COLL_ENDPOINTS, COLL_FLOWS, COLL_SUBSYSTEMS, COLL_LOGIC_ARTIFACTS):
        await mongo.collection(coll).create_index(
            [("project_id", pymongo.ASCENDING), ("id", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_LABELS).create_index(
        [("project_id", pymongo.ASCENDING), ("name", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_QUERY_VIEW_CACHE).create_index(
        [("project_id", pymongo.ASCENDING), ("location", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_INDEX_META).create_index("project_id", unique=True)
