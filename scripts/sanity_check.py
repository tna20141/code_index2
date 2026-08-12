#!/usr/bin/env python
# Structural sanity check for the code-index Mongo store. Read-only -- reports problems, changes nothing.
# Checks SCHEMA/REFERENTIAL integrity only (not content quality): required fields present & right type,
# every project_id points at a real project, all cross-references (labels/logic_artifacts/endpoint_ids)
# resolve WITHIN the same project, business keys are unique per project, and no obviously-broken shapes.
#
# Run: uv run python scripts/sanity_check.py            # all projects
#      uv run python scripts/sanity_check.py <slug>     # one project
# Exit code 1 if any problem is found (handy for CI), 0 if clean.

import asyncio
import sys

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

# (collection, business-key field, required str fields, required list[str] fields, ref fields:
#   {field: (target_collection, target_key)})
_ENTITY_SPECS = [
    (COLL_ENDPOINTS, "id",
     ["kind", "handler_location", "trigger"], [],
     {"labels": (COLL_LABELS, "name"), "logic_artifacts": (COLL_LOGIC_ARTIFACTS, "id")}),
    (COLL_FLOWS, "id",
     ["description"], ["endpoint_ids", "labels", "logic_artifacts"],
     {"endpoint_ids": (COLL_ENDPOINTS, "id"), "labels": (COLL_LABELS, "name"),
      "logic_artifacts": (COLL_LOGIC_ARTIFACTS, "id")}),
    (COLL_SUBSYSTEMS, "id",
     ["description", "content"], ["labels", "logic_artifacts"],
     {"labels": (COLL_LABELS, "name"), "logic_artifacts": (COLL_LOGIC_ARTIFACTS, "id")}),
    (COLL_LOGIC_ARTIFACTS, "id",
     ["description"], ["labels"],
     {"labels": (COLL_LABELS, "name")}),
    (COLL_LABELS, "name",
     [], [], {}),
]


class _Report:
    def __init__(self):
        self.problems: list[str] = []

    def add(self, coll: str, key: str, msg: str) -> None:
        self.problems.append(f"[{coll}] {key}: {msg}")


async def _keyset(coll: str, project_id: str, key: str) -> set[str]:
    docs = await mongo.find(coll, {"project_id": project_id}, {key: 1})
    return {d[key] for d in docs if key in d}


async def _check_project(project_id: str, rep: _Report) -> None:
    # cache each collection's valid keys for this project (for ref resolution).
    keysets = {
        coll: await _keyset(coll, project_id, k)
        for coll, k in ((COLL_ENDPOINTS, "id"), (COLL_LABELS, "name"), (COLL_LOGIC_ARTIFACTS, "id"))
    }

    for coll, key_field, str_fields, list_fields, refs in _ENTITY_SPECS:
        docs = await mongo.find(coll, {"project_id": project_id})
        seen_keys: set[str] = set()
        for doc in docs:
            key = doc.get(key_field, "<missing-key>")

            # 1. business key present & non-empty
            if not doc.get(key_field):
                rep.add(coll, "<?>", f"missing/empty business key `{key_field}`")
                continue
            # 2. duplicate business key within the project (unique index should prevent, but check anyway)
            if key in seen_keys:
                rep.add(coll, key, f"duplicate `{key_field}` within project")
            seen_keys.add(key)
            # (project_id validity is checked globally in _check_globals, across all docs.)
            # 4. required string fields present & of type str
            for f in str_fields:
                if f not in doc:
                    rep.add(coll, key, f"missing required field `{f}`")
                elif not isinstance(doc[f], str):
                    rep.add(coll, key, f"field `{f}` should be str, got {type(doc[f]).__name__}")
            # 5. required list fields are lists of str
            for f in list_fields:
                v = doc.get(f, [])
                if not isinstance(v, list):
                    rep.add(coll, key, f"field `{f}` should be a list, got {type(v).__name__}")
                elif any(not isinstance(x, str) for x in v):
                    rep.add(coll, key, f"field `{f}` should contain only strings")
            # 6. referential integrity: every ref resolves within THIS project
            for field, (target_coll, _tkey) in refs.items():
                for ref in doc.get(field, []) or []:
                    if ref not in keysets[target_coll]:
                        rep.add(coll, key, f"dangling {field} ref `{ref}` (no such {target_coll} in project)")


async def _check_globals(valid_projects: set[str], rep: _Report) -> None:
    # projects: id present & unique, root_path present.
    seen = set()
    for p in await mongo.find(COLL_PROJECTS, {}):
        pid = p.get("id")
        if not pid:
            rep.add(COLL_PROJECTS, "<?>", "missing `id`")
            continue
        if pid in seen:
            rep.add(COLL_PROJECTS, pid, "duplicate project id")
        seen.add(pid)
        if not p.get("root_path"):
            rep.add(COLL_PROJECTS, pid, "missing `root_path` (read server can't spread this project)")

    # index_meta + query_view_cache: project_id must be valid; index_meta one-per-project.
    meta_seen = set()
    for m in await mongo.find(COLL_INDEX_META, {}):
        pid = m.get("project_id")
        if pid not in valid_projects:
            rep.add(COLL_INDEX_META, str(pid), "dangling project_id")
        if pid in meta_seen:
            rep.add(COLL_INDEX_META, str(pid), "more than one watermark for this project")
        meta_seen.add(pid)
        if not m.get("commit_hash"):
            rep.add(COLL_INDEX_META, str(pid), "missing commit_hash")

    for c in await mongo.find(COLL_QUERY_VIEW_CACHE, {}):
        if c.get("project_id") not in valid_projects:
            rep.add(COLL_QUERY_VIEW_CACHE, c.get("location", "<?>"), "dangling project_id")

    # entity docs whose project_id points at NO project -- these are invisible to the per-project loop
    # (which only iterates valid projects), so catch them here across every entity collection.
    for coll, key_field, *_ in _ENTITY_SPECS:
        for doc in await mongo.find(coll, {}):
            if doc.get("project_id") not in valid_projects:
                rep.add(coll, doc.get(key_field, "<?>"),
                        f"orphaned project_id `{doc.get('project_id')}` (no such project)")


async def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    mongo.connect()

    projects = await mongo.find(COLL_PROJECTS, {})
    valid_projects = {p["id"] for p in projects if p.get("id")}
    target_ids = [only] if only else sorted(valid_projects)
    if only and only not in valid_projects:
        print(f"No such project: {only}")
        await mongo.close()
        return 1

    rep = _Report()
    await _check_globals(valid_projects, rep)
    for pid in target_ids:
        await _check_project(pid, rep)

    await mongo.close()

    scope = f"project '{only}'" if only else f"{len(target_ids)} project(s)"
    if not rep.problems:
        print(f"OK -- no structural problems found ({scope}).")
        return 0
    print(f"Found {len(rep.problems)} problem(s) ({scope}):")
    for p in rep.problems:
        print("  -", p)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
