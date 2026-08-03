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


async def ensure_indexes() -> None:
    await mongo.collection(COLL_PROJECTS).create_index("id", unique=True)
    for coll in (COLL_ENDPOINTS, COLL_FLOWS, COLL_SUBSYSTEMS, COLL_LOGIC_ARTIFACTS):
        await mongo.collection(coll).create_index(
            [("project_id", pymongo.ASCENDING), ("id", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_LABELS).create_index(
        [("project_id", pymongo.ASCENDING), ("name", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_QUERY_VIEW_CACHE).create_index(
        [("project_id", pymongo.ASCENDING), ("location", pymongo.ASCENDING)], unique=True)
    await mongo.collection(COLL_INDEX_META).create_index("project_id", unique=True)
