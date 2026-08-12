#!/usr/bin/env python
# Move a repo's .codeindex.config.js `endpoint_types` into its `projects` DB row (config centralization).
# Reads the JS config via node (eval -> JSON), then writes endpoint_types onto the project row.
#
# Run (dry-run, prints what it would set):
#   uv run python scripts/import_config_to_project.py <project_id> <path/to/.codeindex.config.js>
# Apply:
#   uv run python scripts/import_config_to_project.py <project_id> <path/to/.codeindex.config.js> --apply

import asyncio
import json
import subprocess
import sys

from src.repositories import COLL_PROJECTS
from src.utils import mongo


def _read_js_config(config_path: str) -> dict:
    # eval the JS config with node and get JSON back (the config is JS, not JSON-parseable directly).
    out = subprocess.run(
        ["node", "-e", f"console.log(JSON.stringify(require('{config_path}')))"],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


async def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv
    if len(args) != 2:
        print("usage: import_config_to_project.py <project_id> <config.js path> [--apply]")
        return 1
    project_id, config_path = args

    config = _read_js_config(config_path)
    endpoint_types = config.get("endpoint_types") or config.get("endpointTypes") or []
    if not endpoint_types:
        print("No endpoint_types found in the config.")
        return 1

    mongo.connect()
    project = await mongo.find_one(COLL_PROJECTS, {"id": project_id})
    if project is None:
        print(f"No such project row: {project_id} (seed it first with id + root_path).")
        await mongo.close()
        return 1

    kinds = [e.get("kind") for e in endpoint_types]
    print(f"Project '{project_id}': would set endpoint_types = {len(endpoint_types)} kinds: {kinds}")
    if not apply:
        print("(dry run -- pass --apply to write)")
        await mongo.close()
        return 0

    await mongo.update_one(COLL_PROJECTS, {"id": project_id}, {"endpoint_types": endpoint_types})
    print("Applied.")
    await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
