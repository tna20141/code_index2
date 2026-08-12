# Integration-ish tests for the curation service against a LIVE local Mongo (available per the setup).
# Covers project-scoped reference validation (reject dangling), cascade delete (purge refs), and that a
# skeleton update preserves curation. Uses a throwaway db name so it never touches real data.

import pytest

from src.services import curation
from src.services.curation import DanglingReferenceError
from src.utils import mongo

pytestmark = pytest.mark.asyncio

_P = "proj1"  # the test project_id


def _endpoint(eid: str, labels=None) -> dict:
    return {"project_id": _P, "id": eid, "kind": "http", "handler_location": "src/x.py:handler",
            "trigger": "GET /x", "description": "", "annotation": "",
            "labels": labels or [], "logic_artifacts": [], "last_scanned_commit": ""}


@pytest.fixture(autouse=True)
async def _clean_db(monkeypatch):
    monkeypatch.setattr(mongo.settings, "mongo_db", "code_index2_test")
    mongo.connect()
    for c in ("endpoints", "flows", "subsystems", "logic_artifacts", "labels"):
        await mongo.collection(c).drop()
    yield
    await mongo.close()


async def test_create_flow_rejects_dangling_endpoint():
    with pytest.raises(DanglingReferenceError) as exc:
        await curation.create_flow({"project_id": _P, "id": "f1", "description": "",
                                    "endpoint_ids": ["nope"], "labels": [], "logic_artifacts": [],
                                    "last_scanned_commit": ""})
    assert "endpoint:nope" in str(exc.value)
    assert await mongo.find_one("flows", {"id": "f1"}) is None  # nothing written


async def test_ref_validation_is_project_scoped():
    # an endpoint in another project does NOT satisfy a ref in _P.
    await curation.create_endpoint({**_endpoint("e1"), "project_id": "other"})
    with pytest.raises(DanglingReferenceError):
        await curation.create_flow({"project_id": _P, "id": "f1", "description": "",
                                    "endpoint_ids": ["e1"], "labels": [], "logic_artifacts": [],
                                    "last_scanned_commit": ""})


async def test_delete_label_cascades_within_project():
    await curation.create_label({"project_id": _P, "name": "dep", "description": ""})
    await curation.create_endpoint(_endpoint("e1", labels=["dep"]))
    await curation.create_flow({"project_id": _P, "id": "f1", "description": "", "endpoint_ids": ["e1"],
                                "labels": ["dep"], "logic_artifacts": [], "last_scanned_commit": ""})

    await curation.delete_label(_P, "dep")

    assert (await mongo.find_one("endpoints", {"project_id": _P, "id": "e1"}))["labels"] == []
    assert (await mongo.find_one("flows", {"project_id": _P, "id": "f1"}))["labels"] == []


async def test_delete_endpoint_cascades_to_flow_endpoint_ids():
    await curation.create_endpoint(_endpoint("e1"))
    await curation.create_flow({"project_id": _P, "id": "f1", "description": "", "endpoint_ids": ["e1"],
                                "labels": [], "logic_artifacts": [], "last_scanned_commit": ""})

    await curation.delete_endpoint(_P, "e1")

    assert (await mongo.find_one("flows", {"project_id": _P, "id": "f1"}))["endpoint_ids"] == []


async def test_update_endpoint_partial_leaves_omitted_fields():
    # a partial update writes only the passed fields; omitted ones (e.g. curation) are untouched.
    await curation.create_endpoint({**_endpoint("e1"), "trigger": "GET /old", "description": "curated"})
    await curation.update_endpoint(_P, "e1", {"trigger": "GET /new", "last_scanned_commit": "b"})
    ep = await mongo.find_one("endpoints", {"project_id": _P, "id": "e1"})
    assert ep["trigger"] == "GET /new" and ep["description"] == "curated"


async def test_update_endpoint_ignores_protected_keys():
    await curation.create_endpoint(_endpoint("e1"))
    await curation.update_endpoint(_P, "e1", {"id": "hacked", "project_id": "other", "trigger": "GET /y"})
    ep = await mongo.find_one("endpoints", {"project_id": _P, "id": "e1"})
    assert ep is not None and ep["trigger"] == "GET /y"  # id/project_id whitelisted out, not written
