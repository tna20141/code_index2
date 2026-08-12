# Project Documents Feature — Design

Lets a project expose a curated set of **verbatim documents** (files/folders in the indexed repo) to the
read-MCP agent — reference material (architecture notes, ADRs, domain docs) the agent can fetch alongside
the code-navigation tools. Access is allowlist-gated.

## Storage

The `projects` collection row gains an optional field:

```
documents: [
  { path: "docs/architecture.md", description: "System architecture overview. Fetch when reasoning about component boundaries." },
  { path: "docs/adr/",            description: "Architecture decision records. Fetch when a design choice needs its rationale." }
]
```

- **Seeded by hand** (like `root_path`); nothing auto-creates it. Absent/empty → the project simply has no documents.
- `path` is **repo-root-relative**. A **trailing `/`** marks a **directory entry** (recursive access); no slash = a **single file**.
- `description` is freetext for the agent: what the doc is and when to fetch it.

## Allowlist model (the security core)

A requested path is **allowed** iff — after resolving BOTH the request and the allowlist entry to realpaths
under the project's `root_path`:

- it **equals** a file-entry's realpath, **OR**
- it is **at or under** a directory-entry's realpath (`realpath(req).startswith(realpath(dir) + os.sep)`, or equals the dir).

`realpath` on both sides defeats `../` traversal and symlink escapes. A path resolving **outside `root_path`**
is always rejected. Directory access is **recursive**: any descendant file/subdir of an allowed directory
entry is reachable.

## Tools (read MCP; all take `project_id`)

### `list_documents(project_id)`
Returns the `documents` array ~verbatim: `[{path, description}]`. The catalog — tells the agent what exists
and when to fetch. Empty list if none configured.

### `read_documents(project_id, paths: list[str])`
Read one or more files and/or directories (mixed allowed in one call).
- **Validate ALL paths first** against the allowlist. If ANY is disallowed/escaping → **reject the whole
  call** with a single error (nothing read).
- File path → read that file. Directory path → read **all files recursively** under it (any depth).
- **All files, no extension filter** (the allowlist already scopes reachability).
- Output: one concatenated string, each file delimited by a marker:
  ```
  ===== FILE: docs/architecture.md =====
  <contents>

  ===== FILE: docs/adr/0001-use-mongo.md =====
  <contents>
  ```
- A file that can't be UTF-8 decoded → a `[unreadable: <path>]` line in place of its contents (does NOT fail
  the batch; only allowlist violations fail the whole call).

### `list_directory(project_id, path)`
Lists the **immediate** (non-recursive) contents of an allowed directory — files and subdirs. Subdirs can be
further `list_directory`'d; files can be `read_documents`'d. `path` must be allowed (a directory entry or a
descendant dir of one); otherwise error.

## Placement

- **`src/services/documents.py`** — new service: the allowlist containment logic + file/dir reading. Its own
  concern (reusable, unit-testable without MCP).
- **`src/mcp/read_server.py`** — three thin controller tools wiring to the service.
- **`Project` DTO** (`src/dto.py`) — add `documents: NotRequired[list[dict]]`.
- Allowlist containment reuses the realpath pattern from `boundary.is_library_call` (factor a small
  `_is_within(abs_path, abs_root)` helper if it reads cleaner).

## Flows & branches

`read_documents(paths)`:
1. Load the project's `documents` allowlist (from the row). None → error "no documents configured".
2. For each requested path: resolve to abs realpath; classify allowed (file-match / under-dir) or not.
3. ANY disallowed → return `{error}` (reject whole call).
4. All allowed → for each: if dir, walk recursively collecting files; if file, take it. Read each; decode
   failures become `[unreadable: <path>]`. Concatenate with markers → `{content}`.

`list_directory(path)`:
1. Allowlist-check `path` (must be an allowed directory). Not allowed / not a dir → `{error}`.
2. Return immediate entries: `[{name, path, type: "file"|"dir"}]`.

`list_documents()`: read the row's `documents`, return it (or `[]`).

## Error cases

- No `documents` on the project → `list_documents` returns `[]`; `read`/`list_directory` return a clear
  "no documents configured for this project" error.
- Disallowed / `../`-escaping / symlink-escaping path → whole-call rejection.
- Nonexistent file or dir (even if allowlisted) → error.
- Non-UTF-8 file during a read → `[unreadable: <path>]` inline, batch continues.
- Unknown/unseeded project → the existing `UnknownProject` path (same as other read tools).

## Testing

- **Allowlist unit tests** (pure, no MCP): file-entry exact match; dir-entry descendant allowed; sibling of
  an allowed file denied; `../` escape denied; symlink escape denied; path outside root denied.
- **read/list behavior** against a temp dir tree: recursive read collects nested files; mixed files+dirs in
  one call; marker format; non-UTF-8 → `[unreadable]`; one disallowed path rejects the whole batch.
- `list_documents` returns the seeded array verbatim.

## Non-goals

- No writing/editing of documents (read-only).
- No extension filtering / binary detection (all files; allowlist is the gate).
- No config-file (`.codeindex.config.js`) involvement — the list lives in the DB row, machine-read.
