# Intentions: classify a resolved call site -- does spread descend into it, or is it a leaf? The three
# mechanical stop-rules from docs/spec.md section 2: library boundary (definition outside repo_root),
# trivial marker (# ci:trivial), repo-frontier (repository-layer path). Pure, so it's directly testable.

import os

from src.constants import TRIVIAL_MARKER
from src.services.spread.lsp import Definition

# Path fragments that mark the repository layer -- functions here are spread frontiers (their callees are
# the DB driver = a library boundary). Matches evolix's src/repositories/ and modules/*/repositories/.
_REPO_LAYER_MARKERS = ("/repositories/", "/repository.py")

# Path segments that mean "third-party/stdlib code" even when they live UNDER repo_root -- a project's own
# .venv/site-packages sits inside the repo dir but is NOT the project's code. Checked in addition to the
# outside-root test so a nested venv is correctly a library boundary.
_LIBRARY_SEGMENTS = ("/site-packages/", "/.venv/", "/dist-packages/")


def is_library_call(definition: Definition, root_path: str) -> bool:
    """[Pure-ish] True if the definition is third-party/stdlib -- either resolving OUTSIDE `root_path` (the
    active project's repo root), or under a vendored segment (site-packages / .venv) that happens to nest
    inside it. realpath on both sides so editable installs / symlinks don't fool the prefix check."""
    resolved = os.path.realpath(definition["path"]).replace(os.sep, "/")
    root = os.path.realpath(root_path)
    if not resolved.startswith(root.replace(os.sep, "/") + "/"):
        return True
    return any(seg in resolved for seg in _LIBRARY_SEGMENTS)


def is_repo_frontier(definition: Definition) -> bool:
    """[Pure] True if the definition lives in the repository layer -- a query frontier. Spread stops here and
    captures the query (see query_view). Path-based so it's independent of the resolver."""
    path = definition["path"].replace(os.sep, "/")
    return any(marker in path for marker in _REPO_LAYER_MARKERS)


def is_trivial(def_leading_lines: list[str]) -> bool:
    """[Pure] True if the # ci:trivial magic comment appears in the def's leading block (the decorator/comment
    lines materialize.py already read above the def). A trivial function is a leaf: spread won't descend."""
    return any(line.strip().startswith(TRIVIAL_MARKER) for line in def_leading_lines)
