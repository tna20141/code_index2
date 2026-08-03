# Code Index 2

A code-navigation index for Python codebases, exposed as two MCP servers. Built for evolix but reusable
for any Python project. Design: [`docs/spec.md`](docs/spec.md).

## What it is

A **sparse, curated meaning layer over live code** — endpoints, flows, subsystems, logic artifacts, and
labels persisted in MongoDB, with the call-chain **spread** computed live from source (nothing structural
persisted → no drift). Two MCP servers:

- **read** (`code-index`) — `spread` (inline an endpoint's call chain into a reading view), `list` (filtered
  entity queries), `search` (semantic).
- **admin** (`code-index-admin`) — full CRUD on entities (with reference validation + cascade delete) and the
  global commit-hash watermark.

## Layout

```
src/config.py            runtime config (dotenv, mirrors evolix)
src/constants.py         entity/kind/mode enums + spread markers
src/dto.py               persisted entity shapes (TypedDict)
src/utils/               mongo (motor wrapper), git, claude (-p for query views)
src/repositories/        one module per Mongo collection
src/services/curation.py write-side: validation + cascade
src/services/reads.py    list/getter + target resolution
src/services/search.py   voyage-code-3 + FAISS
src/services/spread/     the call-chain traversal (resolver seam, boundary, materialize, render, query_view)
src/mcp/                 read_server / admin_server / auth
main_read.py, main_admin.py   ASGI entry points (pm2 targets)
```

## Run

```bash
uv sync
cp .env.example .env.local          # fill VOYAGE_API_KEY, tokens; point REPO_ROOT at the indexed repo
pm2 start ecosystem.config.js       # or: uv run uvicorn main_read:app --port 8210
```

The read MCP resolver defaults to **pyright** (via multilspy — needs Node). Swap to jedi by setting
`RESOLVER_BACKEND=jedi` once `lsp_jedi.py` exists; nothing else changes (see the `Resolver` seam in
`src/services/spread/lsp.py`).

## Test

```bash
uv run ruff check
uv run pytest tests/unit
```
