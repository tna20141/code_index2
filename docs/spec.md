# CODE INDEX 2 — DESIGN SPEC

A code-navigation index for Python codebases, exposed as MCP servers. Built for evolix
(the `evolix-backend` FastAPI codebase) but reusable for any Python-based project.

Supersedes the design in `evolix-backend/docs/codeindex.md`. The prior implementation at
`aagent/src/code_index/` is **reference only** — this spec is authoritative.

---

## 1. Core model

The index is a **sparse, curated meaning layer over live code** — not a dense structural
mirror. The source code is the single source of truth; we persist only curated meaning on
top of it. Anything derivable from the code (call chains, bodies) is **computed live, not
stored** — avoiding the sync/drift that a persisted structural graph would incur.

Five entity types:

- **Endpoint** — the entry point of a triggered execution: an HTTP route handler, a Kafka
  consumer handler, or a job handler. Auto-generated from the codebase, then annotated
  semi-manually (LLM pre-generates description/annotation, human reviews).
- **Flow** — a curated grouping of endpoints (and prose) that are tightly related
  business- or technically (e.g. a CRUD set, an OAuth flow, a tenant-onboarding flow).
- **Subsystem** — a larger curated grouping for a self-contained module/subsystem, with a
  long-form markdown description.
- **Logic artifact** — a named quirk/convention/distinctive logic worth referencing by name.
- **Label** — controlled vocabulary for cataloging/lookup; lean and manually managed.

Relationships (all references stored as the target's business `id` slug, never ObjectId):

- Flow → Endpoint, Subsystem → Endpoint (1-n, non-strict: an endpoint may appear in many).
- Every entity carries its own `labels[]`. Endpoints/flows/subsystems also carry
  `logic_artifacts[]` (artifacts applying to the whole entity). Artifacts carry `labels`
  but **not** `logic_artifacts`.
- Ownership rule: the referencing entity owns the reference (flows/subsystems own
  `endpoint_ids`; entities own their `labels`/`logic_artifacts`). There is **no** reverse
  `applies_to` and **no** separate edge collection.

---

## 2. Spread — live call-chain traversal

The primary navigation mechanism: start at an endpoint (or any function) and inline the
whole call chain into one **reading-only** stitched-source artifact (never runnable Python).

Each descended call site is replaced by the callee's body (including its leading
intention-comments), bracketed by name-matched markers:

```
# && spread-begin: <path-from-repo-root>:<name>
...callee body (with its leading comments)...
# && spread-end: <path-from-repo-root>:<name>
```

Structure is recovered from the **name-matched begin/end pairs**, not indentation.

**Two render modes:**
- `indented` — callee body left-padded to the caller's current indentation (nests visually).
- `flat` — natural indentation; structure carried by markers alone.

**Stop signals (leaves — do not descend; call line left as-is, no marker):**
1. **Library boundary** — the callee's definition resolves (via LSP) to a path outside the
   configured repo root. Detection: `os.path.realpath(def_path)` not under
   `os.path.realpath(repo_root)`; builtins (no def file) also stop. `realpath` on both sides
   handles venvs / editable installs / symlinks.
2. **Trivial marker** — a `# ci:trivial` magic comment on/above the `def`. Detected by
   scanning the def line + decorator block + immediately-preceding comment lines (already
   read while capturing the body). No runtime import in the indexed codebase — a comment
   convention travels to any repo.
3. **Repo-frontier** — a function under the repository layer. Naturally a leaf (its callees
   are the DB driver = a library boundary). Its query text is captured as content; see §3.

**Content materialization per node:** resolve definition (LSP: where + span) → boundary check
→ read the span, extending **upward** while preceding lines are comments/decorators to
capture the full leading intention-comment block. Docstrings and inline comments come for
free (they live inside the read span).

**LSP:** **pyright** via `pyright-langserver --stdio` (max resolving power; reusable across
Python codebases). The MCP owns the pyright subprocess lifecycle (spawn on boot, terminate
on shutdown). Do **not** hand-roll the raw protocol — use a managed client wrapper. `repo_root`
is fixed config per indexed project. Index reflects **HEAD** (committed state), not a dirty
working tree.

---

## 3. Repo/query inlining

A repo-frontier function's leaf content = its **verbatim body** (always, source of truth)
**plus** an optional **derived "inlined query view"**: the private query-building helpers
inlined back into one coherent, de-indirected query block, redundant indirection cut, so a
reader sees the whole query as one thing. This is a *readability refactor* that preserves
logic — never fabricated runtime values, never overwriting the real body.

- **Generation:** on-demand, during `spread`, in the **read MCP** at the repo layer. Shells
  out to `claude -p` (Haiku) to produce the inlined view. It must flag anything it cannot
  faithfully inline (honest partial over confident-wrong).
- **Failure handling:** `claude -p` fails → retry once → still failing → fall back to
  deterministic (serve verbatim body only). `spread` never hard-fails on LLM trouble.
- **Cache:** keyed by **commit SHA**. Miss only on first navigation after a commit that
  changed the code. A new commit invalidates and regeneration resets `approved: false`
  (prior human approval was for the old code). Stored in a dedicated `query_view_cache`
  collection (not an entity).

---

## 4. Storage — MongoDB

`_id` is Mongo's auto `ObjectId` everywhere. A separate business `id` slug is the
human/deterministic identifier used in all cross-references. Every entity carries
`last_scanned_commit` (the codebase SHA at last scan/curation — informational for curated
entities, a staleness signal). Cross-refs store the target's `id` slug.

**Unique indexes:** `endpoints.id`, `flows.id`, `subsystems.id`, `logic_artifacts.id`,
`labels.name`.

(All entities also carry `project_id` — the tenant discriminator; uniqueness is compound `{project_id, key}`.)

### `endpoints` (auto-generated + semi-manual annotation)
```
_id, project_id, id         # id: DERIVED FROM THE TRIGGER per the config's idRule (no spaces/special chars,
                            #     no file path -> stable across rescans). Shape "<kind>__<trigger>",
                            #     e.g. "http__POST_api_v1_shops", "periodic_job__amz_poll_task"
kind                        # free string; kinds declared in the codebase's .codeindex.config.js
                            #   (evolix: "http" | "kafka" | "periodic_job" | "worker_handler")
handler_location            # "{path-from-root}:{symbol}" — the handler's def NAME (no line number, so it
                            #   survives unrelated edits; the line is resolved live via LSP at spread start)
trigger                     # route / topic / job-name — the external trigger (the id derives from it)
description                 # curated; annotation? (optional) — curated free-text
labels[], logic_artifacts[]
last_scanned_commit
created_at, updated_at
```

### `flows` (curated)
```
_id, project_id, id (slug), description
endpoint_ids[]
labels[], logic_artifacts[]
last_scanned_commit, created_at, updated_at
```

### `subsystems` (curated)
```
_id, project_id, id (slug)
description                  # short summary
content                     # long-form markdown; endpoint AND flow refs live inline in prose (no id arrays)
labels[], logic_artifacts[]
last_scanned_commit, created_at, updated_at
```

### `logic_artifacts` (curated)
```
_id, id (slug + random suffix), description   # describe + implications + examples
labels[]                                       # no logic_artifacts
last_scanned_commit, created_at, updated_at
```

### `labels` (controlled vocabulary)
```
_id, name (unique), description, created_at, updated_at
```

### `projects` (multi-project bucket)
```
_id, id (slug, unique), root_path, documents?, created_at, updated_at
```
`documents?` is an optional allowlist of verbatim reference files/folders exposed to the read MCP:
`[{path (repo-root-relative; trailing "/" = a recursive directory), description}]`. Seeded by hand.
Powers the `list_documents` / `read_documents` / `list_directory` read tools (see
`docs/documents-feature-design.md`).
One row per indexed codebase, keyed by the canonical slug (matching its `.codeindex.config.js`
`project`). `root_path` is the codebase's source location **on the server** — the single host of
record, so read users need no local clone and no registration: they pass a `project_id`, and the
read server resolves/spreads against `root_path` (resolver started **lazily** on first spread).
Seeded by hand (id + root_path); nothing auto-creates it.

### `query_view_cache` (non-entity)
```
_id, project_id, location ("{path}:{func}"), content, commit_sha, approved, generated_at
```

### `index_meta` (per-project watermark)
```
_id, project_id (unique), commit_hash, updated_at
```
Per-project "the index reflects this commit" watermark (one row per project), separate from the
per-entity `last_scanned_commit`. Authoritative base for the scanning agent's `git diff`
(§7) and the signal of a project's index freshness.

---

## 5. MCP tool surface — two servers

Split per the spec: a **read** MCP for navigation, a **maintain** MCP for curation. Separate
processes (pm2). HTTP/SSE transport, exposable via nginx (HTTPS), no SSH tunnel required.
**Auth:** exact-token match on both; **different tokens** per MCP (scope/revoke independently),
distributed by hand.

Every tool takes `project_id` (the slug). No registration — the read server reads each project's
server-side `root_path` from the `projects` row and starts its resolver lazily.

### Read MCP (`code-index`)
- **`list(project_id, entity_type, ids?, labels?, logic_artifacts?, kind?, select?)`** — AND-combined
  filters; also the getter (pass `ids`); `select` projects fields.
- **`search(project_id, query, entity_types?, top_k?)`** — semantic search (§6); returns ranked
  ids+scores; caller `list`s the ids.
- **`spread(project_id, endpoint_id?|location?|symbol?, path?, mode?, max_depth?)`** — the live
  call-chain stitch (§2). Target by endpoint id, `path:lineno` location, or symbol name
  (precedence in that order; `path` scopes a symbol; a symbol with >1 match returns them + a
  warning). Repo-frontier triggers `claude -p` query-view (§3), cached by SHA.
- **`discover(project_id, symbol, path?)`** — locate a symbol (LSP workspace-symbol) → matches
  `{symbol, path, line, kind, container?}`. `path` scopes to one file.
- **`list_projects()`** — the available project slugs.

### Maintain MCP (`code-index-admin`)
- **Full CRUD** — `create_/update_/delete_` × {endpoint, flow, subsystem, logic_artifact,
  label}.
- **Write-time validation** — create/update reject dangling references (referenced endpoint
  /label/artifact ids must exist).
- **Delete = cascade purge** — deleting an entity `$pull`s its id from every referencing
  array (endpoint → flows' `endpoint_ids`; label → all `labels`; artifact → all
  `logic_artifacts`). Subsystems reference endpoints/flows inline in `content` prose (no id
  array) so nothing cascades there. Multi-collection, non-transactional (acceptable for a
  single-writer internal tool; see §7 TODO).
- **`get_commit_hash()` / `set_commit_hash(hash)`** — read/write the global index watermark
  (`index_meta`, §4). The scanning agent reads it to diff against HEAD, and sets it after a
  successful scan pass.

---

## 6. Semantic search

- **Model:** `voyage-code-3` (1024-dim), code-domain-tuned. API key from env/config, never
  hardcoded. Query embedded with the same model.
- **Index:** **FAISS `IndexFlatL2`** on disk, one file per entity type (brute-force k-NN is
  instant at our scale). Search = load index → embed query → k-NN → filter by distance
  threshold → return ids+scores.
- **Build:** full rebuild, **manually triggered** for now (workflow later — §7 TODO).
- **Embedded text per entity** (curated meaning + light structural/associative signal):
  - endpoint → `id` + `description` + `annotation` + `trigger` + the live
    **spread** (regenerated at build time — the index is a point-in-time snapshot).
  - flow → `id` + `description` + referenced endpoint-id slugs.
  - subsystem → `id` + `description` + `content`.
  - logic_artifact → `id` + `description`.
  - labels → **not embedded** (exact-match vocabulary).

---

## 7. Endpoint auto-generation

A **scanning agent** (not a special MCP tool) drives generation via the maintain MCP. The
agent-facing runbook is `docs/seeding.md`; the admin MCP's `instructions` field carries the
same workflow. Seeding (first time) and incremental updates share one mechanism — scope is
derived from the watermark, not a mode flag.

**Discovery contract — `.codeindex.config.js`** (at the *indexed repo's* root, read by the
agent as text, not machine-parsed). Declares `endpointTypes: [{kind, description, howToFind,
paths[]}]` so the agent knows what to look for and where. This keeps code_index2
codebase-agnostic (reusable for any Python repo = drop a config in that repo). The four kinds:
**http** (FastAPI `@router.<method>`), **kafka** (consumer loop), **periodic_job**
(`@periodic_job`), **worker_handler** (`@worker_sprint`).

1. Read `.codeindex.config.js`. Scope via `get_commit_hash()`: **null → first seed** (sweep the
   whole tree / config folders for every kind); **set → incremental** (`git diff <watermark>..HEAD`,
   changed files only). After a successful pass, `set_commit_hash(HEAD)`.
2. Classify affected endpoints as new / changed / removed (per each kind's `howToFind`).
3. Drive CRUD: create new (skeleton), update changed via `update_endpoint` (passing only the
   auto-scanned fields, omitting curated ones so curation isn't clobbered), delete removed
   (cascade purges references).
4. Annotate each new/changed endpoint: `spread(id)` (read MCP) → `update_endpoint` with the curated fields.

Deterministic `id`: derived from the **trigger** via the config's per-kind `idRule` (no file path, so a
file move doesn't churn it) — re-scannable and idempotent.
`update_endpoint` writes only the fields passed, so a rescan (scanned fields only) and a curation edit
(curated fields only) don't clobber each other — the split is by convention now, not two tools.

---

## 8. Tech stack & deployment

- Python; MongoDB (local for dev; deployed on the OVH server). Persistence: 5 entity
  collections + `query_view_cache`; FAISS index files on disk.
- pyright language server (subprocess, lifecycle-managed by the MCP).
- `claude -p` (Haiku) for query-view inlining.
- FAISS + `voyage-code-3` for semantic search.
- pm2 for MCP process management. HTTP/SSE transport behind nginx (HTTPS + token auth).
  Recommendation: the maintain MCP is the privileged, money-spending, mutating surface —
  gate it with its own token (and consider keeping it off the public interface entirely).

---

## 9. Future work (deferred TODOs)

- **Self-correcting cascade sweep** — a periodic job to purge any stale references left by a
  crash mid-cascade (the non-transactional delete in §5).
- **Incremental / auto reindex** — replace manual full-rebuild of the FAISS index with
  embed-on-write or a scheduled workflow.
- **Periodic curation-staleness sweep** — flag endpoints/flows whose `last_scanned_commit`
  lags far behind HEAD for re-review (lenient; only stark changes trigger updates).
- **Resolver startup-reaper** — on server boot, kill any stray `jedi-language-server` processes
  left orphaned by a *hard* kill (SIGKILL/OOM) of a prior instance. The registry's SIGTERM/SIGINT
  handler + the ASGI lifespan already tear down resolvers on graceful/normal shutdown; only an
  uncatchable hard kill leaks (the LSP runs in its own process group, so it's not killed with the
  parent). A reaper bounds that leak to "between crash and next restart."
