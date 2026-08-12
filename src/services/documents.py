# Intentions: the project-documents feature -- expose a curated, allowlisted set of verbatim reference files/
# folders (from the indexed repo) to the read MCP. The allowlist lives on the `projects` row (`documents`).
# This service owns (1) allowlist containment (realpath-based, escape-proof) and (2) reading/listing within
# it. Read-only. References: docs/documents-feature-design.md.

import os

from src.repositories import projects as projects_repo


class DocumentAccessError(Exception):
    """A requested path is not in the project's allowlist (or escapes it). The whole read/list call fails."""


class NoDocumentsConfigured(Exception):
    """The project has no `documents` allowlist configured."""


async def list_documents(project_id: str) -> list[dict]:
    """The project's document catalog -- [{path, description}], ~verbatim from the row. [] if none."""
    project = await projects_repo.get(project_id)
    return list(project.get("documents") or []) if project else []


async def _allowlist(project_id: str) -> tuple[str, list[dict]]:
    """(abs root_path, documents allowlist) for the project. Raises NoDocumentsConfigured if empty."""
    project = await projects_repo.get(project_id)
    docs = (project or {}).get("documents") or []
    if not project or not docs:
        raise NoDocumentsConfigured(f"no documents configured for project '{project_id}'")
    return os.path.realpath(project["root_path"]), docs


def _is_within(abs_path: str, abs_dir: str) -> bool:
    # [Pure] True if abs_path is abs_dir itself or a descendant. Both must be realpath'd already.
    return abs_path == abs_dir or abs_path.startswith(abs_dir + os.sep)


def _resolve_allowed(req_path: str, root: str, docs: list[dict]) -> str:
    """Resolve a repo-relative request to an abs realpath, allowed ONLY if it exactly matches a file entry or
    sits under a directory entry (trailing '/'), and stays within root. Raises DocumentAccessError otherwise.
    realpath on both sides defeats ../ traversal and symlink escapes."""
    abs_req = os.path.realpath(os.path.join(root, req_path.lstrip("/")))
    if not _is_within(abs_req, root):
        raise DocumentAccessError(f"path escapes the project root: {req_path}")
    for entry in docs:
        entry_path = entry.get("path", "")
        abs_entry = os.path.realpath(os.path.join(root, entry_path.lstrip("/")))
        if entry_path.endswith("/"):
            if _is_within(abs_req, abs_entry):  # dir entry -> any descendant allowed
                return abs_req
        elif abs_req == abs_entry:              # file entry -> exact match only
            return abs_req
    raise DocumentAccessError(f"path not in the project's document allowlist: {req_path}")


def _read_file(abs_path: str, rel_path: str) -> str:
    # one file as a marker-delimited block; non-UTF-8 -> an [unreadable] placeholder (doesn't fail the batch).
    header = f"===== FILE: {rel_path} ====="
    try:
        with open(abs_path, encoding="utf-8") as f:
            return f"{header}\n{f.read()}"
    except (UnicodeDecodeError, OSError):
        return f"{header}\n[unreadable: {rel_path}]"


def _rel(abs_path: str, root: str) -> str:
    return os.path.relpath(abs_path, root)


async def read_documents(project_id: str, paths: list[str]) -> str:
    """Read the given files and/or directories (mixed OK). ALL paths are allowlist-checked FIRST; if any is
    disallowed the whole call fails (DocumentAccessError). A directory is read RECURSIVELY (all files at any
    depth). Returns one concatenated string, each file marker-delimited. Missing file/dir -> DocumentAccessError."""
    root, docs = await _allowlist(project_id)
    resolved = [_resolve_allowed(p, root, docs) for p in paths]  # raises before any read if any is disallowed

    blocks: list[str] = []
    for abs_path in resolved:
        if os.path.isdir(abs_path):
            for dirpath, _, files in os.walk(abs_path):
                for name in sorted(files):
                    fp = os.path.join(dirpath, name)
                    blocks.append(_read_file(fp, _rel(fp, root)))
        elif os.path.isfile(abs_path):
            blocks.append(_read_file(abs_path, _rel(abs_path, root)))
        else:
            raise DocumentAccessError(f"not found: {_rel(abs_path, root)}")
    return "\n\n".join(blocks)


async def list_directory(project_id: str, path: str) -> list[dict]:
    """Immediate (non-recursive) contents of an allowed directory: [{name, path, type: 'file'|'dir'}]. The
    path must resolve to an allowed directory. Raises DocumentAccessError otherwise."""
    root, docs = await _allowlist(project_id)
    abs_dir = _resolve_allowed(path, root, docs)
    if not os.path.isdir(abs_dir):
        raise DocumentAccessError(f"not a directory: {path}")
    entries = []
    for name in sorted(os.listdir(abs_dir)):
        full = os.path.join(abs_dir, name)
        entries.append({"name": name, "path": _rel(full, root),
                        "type": "dir" if os.path.isdir(full) else "file"})
    return entries
