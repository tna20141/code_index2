# Intentions: shared vocabulary for the index -- entity types, endpoint kinds, spread render modes,
# leaf-stop reasons, and the spread marker/magic-comment literals. Kept central (not scattered) so the
# MCP surface, services, and repos all speak the same strings.

from enum import StrEnum


class EntityType(StrEnum):
    ENDPOINT = "endpoint"
    FLOW = "flow"
    SUBSYSTEM = "subsystem"
    LOGIC_ARTIFACT = "logic_artifact"
    LABEL = "label"


# The entity types that get vectorized for semantic search (labels are exact-match vocabulary, excluded).
SEARCHABLE_ENTITY_TYPES = (
    EntityType.ENDPOINT,
    EntityType.FLOW,
    EntityType.SUBSYSTEM,
    EntityType.LOGIC_ARTIFACT,
)


# NOTE: endpoint `kind` is a free string, NOT an enum here -- the authoritative list of kinds per codebase
# is declared in that repo's .codeindex.config.js (keeps code_index2 codebase-agnostic; another project may
# have kinds we don't know about). Don't reintroduce an EndpointKind enum.


class SpreadMode(StrEnum):
    INDENTED = "indented"  # callee body left-padded to the caller's indentation (nests visually)
    FLAT = "flat"          # natural indentation; structure carried by the markers alone


class LeafReason(StrEnum):
    """Why a spread traversal stopped at a call site instead of descending. Internal classification --
    per the spec the call line is left as-is with no marker; this is for logic/tests, not output."""
    LIBRARY = "library"              # definition resolves outside repo_root
    TRIVIAL = "trivial"              # marked with the # ci:trivial magic comment
    REPO_FRONTIER = "repo_frontier"  # a repository-layer function (query frontier)
    UNRESOLVED = "unresolved"        # the resolver couldn't find a definition
    MAX_DEPTH = "max_depth"          # depth cap reached
    CYCLE = "cycle"                  # callee already on the current spread stack


# Magic comment that marks a function trivial so spread won't descend into its body.
TRIVIAL_MARKER = "# ci:trivial"

# Spread output markers (name-matched begin/end pairs bracket each descended callee).
SPREAD_BEGIN = "# && spread-begin:"
SPREAD_END = "# && spread-end:"

CODE_INDEX_DESC = """
The code index is a to a codebase what an index is for a database table. It helps navigate and explore the codebase faster and with richer context. Currently it only supports Python and is well-suited for Controller-Service-Repository web applications.
It has these main entity types:
- Endpoint: the entrance point that declares an end-to-end execution (e.g. a REST api handler). If you go from all endpoints to all invoked code recursively you should be able to cover the whole codebase (since code must be invoked by something).
- Flow: usually a bunch of related endpoints that are often called together to complete a flow, or are very relevant to each other. Example: a string of APIs sequentially called in a flow, or a CRUD set.
- Subsystem: a broader boundary, usually curated by human with large md-descriptions. There should be few of these in the code index.
- Logic artifact: quirks/specific logics that become common or conventional in the codebase, to the point that they should be named. Mostly curated by human but can ask LLM for suggestions.
- Label: labels tagged to the above entities for arbitrary cataloging. The label list should be tightly controlled though, not extended on a whim.
"""
