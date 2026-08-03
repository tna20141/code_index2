# Intentions: low-level async MongoDB access (shared client + collection handle). Infra plumbing in
# utils/, mirroring evolix's utils/postgres -- repositories call collection()/find helpers, never manage
# the client. Connection-module convention (connect / db / close), same shape as the postgres util.

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from src.config import settings

_client: AsyncIOMotorClient | None = None


def connect() -> None:
    """Create the singleton client ONCE at service startup, before serving. No lock -- startup is
    sequential (no concurrent-first-caller race). Motor connects lazily, so this can't fail on a down DB."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)


def db() -> AsyncIOMotorDatabase:
    assert _client is not None, "mongo not connected; call connect() at startup"
    return _client[settings.mongo_db]


def collection(name: str) -> AsyncIOMotorCollection:
    return db()[name]


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# --- thin operation helpers (dict in / dict out; strip Mongo's _id so callers deal in domain shapes) ---

def _strip_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    # [Pure] drop the ObjectId _id -- callers work with the business `id`/`name`, never the ObjectId.
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if k != "_id"}


async def find_one(coll: str, query: dict, projection: dict | None = None) -> dict | None:
    return _strip_id(await collection(coll).find_one(query, projection))


async def find(coll: str, query: dict, projection: dict | None = None) -> list[dict]:
    cursor = collection(coll).find(query, projection)
    return [d for doc in await cursor.to_list(None) if (d := _strip_id(doc)) is not None]


async def insert_one(coll: str, doc: dict) -> None:
    # insert_one mutates the passed dict by adding _id -- copy so the caller's domain dict stays clean.
    await collection(coll).insert_one({**doc})


async def update_one(coll: str, query: dict, updates: dict, upsert: bool = False) -> int:
    result = await collection(coll).update_one(query, {"$set": updates}, upsert=upsert)
    return result.modified_count


async def upsert_one(coll: str, query: dict, updates: dict, set_on_insert: dict | None = None) -> None:
    """Upsert with a `$setOnInsert` group -- for fields (e.g. created_at) that should be written only when
    the doc is first created, not overwritten on every touch."""
    ops: dict = {"$set": updates}
    if set_on_insert:
        ops["$setOnInsert"] = set_on_insert
    await collection(coll).update_one(query, ops, upsert=True)


async def delete_one(coll: str, query: dict) -> int:
    result = await collection(coll).delete_one(query)
    return result.deleted_count


async def pull_from_all(coll: str, scope: dict, array_field: str, value: str) -> int:
    """$pull `value` from `array_field` of every doc matching `scope` -- the cascade primitive (purge a
    deleted id from all referencing entities WITHIN a project). `scope` (e.g. {'project_id': ...}) keeps the
    cascade from crossing projects. Returns docs modified."""
    result = await collection(coll).update_many(
        {**scope, array_field: value}, {"$pull": {array_field: value}})
    return result.modified_count
