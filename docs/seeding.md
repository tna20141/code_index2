# Seeding & scanning the code index (agent runbook)

Populating the index is **agent-driven** — there is no scan tool. An agent (a `claude -p` run or an
interactive session) with both MCP servers attached does discovery from source and drives the
`code-index-admin` CRUD tools. Seeding (first time) and incremental updates use the **same mechanism**; the
only difference is discovery scope, and that's derived from state (the watermark), not a mode flag.

## Prerequisites

- The project is **seeded in the `projects` collection** by hand: a row `{id: "<slug>", root_path:
  "<server-side source path>"}`. The slug must match the repo's `.codeindex.config.js` `project`.
  (The read server uses `root_path` to spread; nothing auto-creates this row.)
- Both MCP servers running and attached, each with its token:
  - `code-index` (read) — for `spread` / `list` / `search` / `discover` / `list_projects`.
  - `code-index-admin` (maintain) — for CRUD + `get_commit_hash` / `set_commit_hash` / `rebuild_search_index`.
- The **scanning agent runs against its own LOCAL clone** of the target repo (it inspects files directly);
  the repo has a **`.codeindex.config.js`** at its root declaring the endpoint kinds.

## The `.codeindex.config.js` contract

Read by the agent (as text — not machine-parsed). Each entry in `endpointTypes` is
`{ kind, description, howToFind, paths[] }`:

- **kind** — one of `http`, `kafka`, `periodic_job`, `worker_handler`.
- **description** — what this trigger family is.
- **howToFind** — freetext: the decorator/pattern to grep for, how to derive the `trigger`, where the
  handler def is.
- **paths** — the only folders/files to search for this kind (scopes the sweep).

## The flow

```
1. Read <repo>/.codeindex.config.js               -> the endpoint kinds + where/how to find them.
2. get_commit_hash()
     NULL  -> FIRST SEED: sweep the whole tree (the config's folders) for every kind.
     set   -> INCREMENTAL: `git diff <watermark>..HEAD`; only inspect changed files.
3. For each kind, grep its `paths` for the described pattern. For each match derive:
     id               = per the kind's `idRule` in the config, applied to the TRIGGER + shared normalization
                        (no spaces, minimal special chars, no file path/line/handler name). STABLE across
                        rescans -- a file move must not change it.
     kind, handler_location ({path}:{lineno}), signature, trigger
4. Reconcile against the current index (list(entity_type="endpoint")):
     new in source, absent in index      -> create_endpoint(skeleton)
     present in both, scanned-fields chgd -> update_endpoint(id, {scanned fields only})  # omit curated!
     in index, gone from source           -> delete_endpoint(id)   (cascade purges flow endpoint_ids refs)
5. ANNOTATE each new/changed endpoint (the value step):
     spread(id)  (read server)  -> read the whole call chain
     update_endpoint(id, {description, annotation?, labels?, logic_artifacts?})
   On a large first seed, create all skeletons first, then annotate in batches.
6. set_commit_hash(HEAD)        -> so the next run diffs incrementally.
```

## Deriving the `trigger` and the `id` (per kind)

The exact rules (with normalization + examples) live in each project's `.codeindex.config.js` `idRule` —
follow those verbatim. The id shape is always `<kind>__<normalized-trigger>`. In brief for evolix:

- **http** — trigger `METHOD prefix+path` (path from `@router.<method>("path")`; prefix from
  `app.include_router(<router>, prefix=...)` in `src/app.py`). E.g. trigger `POST /api/v1/dashboard/charts`
  → id `http__POST_api_v1_dashboard_charts`.
- **kafka** — trigger = the topic (`settings.kafka_topic`). E.g. `amazon-stream` → `kafka__amazon_stream`.
- **periodic_job** — trigger = the job name (`@periodic_job("name", ...)`; interval NOT in the id). E.g.
  `amz_portfolio_sync` → `periodic_job__amz_portfolio_sync`.
- **worker_handler** — trigger = the sprint name (`@worker_sprint("name")`). E.g. `amz_campaign_update` →
  `worker_handler__amz_campaign_update`.

## Notes

- **Idempotent-ish**: re-running a seed hits unique-`id` conflicts on already-created endpoints — that's the
  "already seeded" signal, harmless. Prefer reconciling (step 4) over blind re-create.
- **Partial updates**: `update_endpoint(id, {...})` writes only the fields you pass. On a rescan, pass only
  the auto-scanned fields (kind/handler_location/signature/trigger/last_scanned_commit) and OMIT the curated
  ones (description/annotation/labels/logic_artifacts) so you don't clobber human curation.
- **Watermark last**: only `set_commit_hash(HEAD)` after a *successful* pass; if the run aborts, leaving the
  old watermark means the next run re-covers the same diff.
- **Flows/subsystems/logic_artifacts/labels** are curated by hand afterward (the agent may suggest them).
  Create a label before referencing it (dangling refs are rejected).
