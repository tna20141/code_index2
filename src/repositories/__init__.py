# Data-access layer: one module per Mongo collection, mirroring the collection list in docs/spec.md
# section 4. Repos deal in domain dicts (DTOs from src/dto), scoped by the business `id`/`name` slug --
# never Mongo's _id. All Mongo access goes through src/utils/mongo; repos never touch motor directly.
# Sealed behind the service layer (services/curation orchestrates writes; MCP never imports repos).

COLL_PROJECTS = "projects"
COLL_ENDPOINTS = "endpoints"
COLL_FLOWS = "flows"
COLL_SUBSYSTEMS = "subsystems"
COLL_LOGIC_ARTIFACTS = "logic_artifacts"
COLL_LABELS = "labels"
COLL_QUERY_VIEW_CACHE = "query_view_cache"
COLL_INDEX_META = "index_meta"
