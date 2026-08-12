# Intentions: the persisted entity shapes (TypedDicts -- the repos return dicts, matching evolix's
# dict-return idiom; not pydantic, which is reserved for MCP tool-input validation). Fields per
# docs/spec.md section 4. Cross-references store the TARGET's business `id` slug (labels: their `name`),
# never Mongo's _id ObjectId.
#
# MULTI-PROJECT: the DB houses many codebases. Every entity carries a `project_id` (the project slug), the
# tenant discriminator -- uniqueness is per-project ({project_id, id}), and every repo query filters by it.
# The abs source path is NOT stored (it's runtime state in the project registry); the `projects` row is just
# the logical bucket.
#
# Endpoints mix auto-scanned fields (kind/handler_location/trigger) and curated fields
# (description/annotation/labels/logic_artifacts). `update_endpoint` writes any subset the caller passes, so
# a rescan should pass only the scanned fields (and omit the curated ones) to avoid clobbering curation.

from datetime import datetime
from typing import NotRequired, TypedDict


class Project(TypedDict):
    """The logical bucket for one indexed codebase AND its config -- everything centralized on this row
    (there is no config file). `id` is the canonical slug. `root_path` is the codebase's source location ON
    THE SERVER -- the single host of record, so read users need no local clone; the read server
    resolves/spreads against it. Seeded by hand."""
    id: str            # slug -- unique
    root_path: str     # absolute source path on the server
    # the endpoint taxonomy the scanning agent uses -- one entry per endpoint kind. Each:
    # {kind, description, how_to_find, id_rule, paths?} (all snake_case). Agent-read prose (not
    # machine-parsed). Seeded by hand.
    endpoint_types: NotRequired[list[dict]]
    # optional allowlist of verbatim reference docs exposed to the read MCP. Each: {path (repo-root-relative;
    # trailing "/" = a directory, recursive access), description}. Seeded by hand.
    documents: NotRequired[list[dict]]
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class Endpoint(TypedDict):
    project_id: str
    # Deterministic id DERIVED FROM THE TRIGGER (no spaces, minimal special chars) -- unique WITHIN a project,
    # stable across rescans (a file move doesn't change it). The exact derivation rule per kind lives in the
    # project's `endpoint_types[].id_rule` (projects row), applied by the scanning agent.
    id: str
    kind: str          # free string; the project's `endpoint_types` (projects row) declares the valid kinds
    # "{path-from-root}:{symbol}" -- where the handler is defined (the def/function name, NOT a line number,
    # so it's stable when unrelated edits shift lines). The line is resolved live via LSP at spread time.
    handler_location: str
    # The external event that INVOKES this endpoint (the id is derived from this):
    # http -> "POST /api/v1/shops"; kafka -> the topic; periodic_job -> "periodic:<name>@<interval>s";
    # worker_handler -> "sprint:<name>".
    trigger: str
    description: str                # curated (LLM pre-gen, human review)
    annotation: NotRequired[str]    # curated free-text -- optional (an endpoint may have none)
    labels: list[str]          # -> labels.name
    logic_artifacts: list[str] # -> logic_artifacts.id
    last_scanned_commit: str
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class Flow(TypedDict):
    project_id: str
    id: str            # slug -- unique WITHIN a project
    description: str
    endpoint_ids: list[str]
    labels: list[str]
    logic_artifacts: list[str]
    last_scanned_commit: str
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class Subsystem(TypedDict):
    project_id: str
    id: str            # slug -- unique WITHIN a project
    description: str   # short summary
    content: str       # long-form markdown; endpoint AND flow refs live inline in the prose (no id arrays)
    labels: list[str]
    logic_artifacts: list[str]
    last_scanned_commit: str
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class LogicArtifact(TypedDict):
    project_id: str
    id: str            # slug + random suffix -- unique WITHIN a project
    description: str   # describe + implications + examples
    labels: list[str]
    last_scanned_commit: str
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class Label(TypedDict):
    project_id: str
    name: str          # unique WITHIN a project -- the label's identifier
    description: str
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class QueryView(TypedDict):
    """Cached inlined-query view for a repo-frontier function. Non-entity: derived, keyed by commit SHA."""
    project_id: str
    location: str      # "{path-from-root}:{func}" -- unique WITHIN a project
    content: str       # the flattened, de-indirected query block
    commit_sha: str    # the commit this view was generated against
    approved: bool     # human vouched for THIS sha's view (resets to False on regeneration)
    generated_at: NotRequired[datetime]


class IndexMeta(TypedDict):
    """Per-project global watermark: the commit that project's index reflects. Base for its scan diff."""
    project_id: str    # unique -- one watermark per project
    commit_hash: str
    updated_at: NotRequired[datetime]
