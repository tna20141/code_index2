# Tests for the project-documents service -- the ALLOWLIST (security-critical) + read/list behavior.
# projects_repo.get is stubbed (no DB); files come from a real tmp tree.

import os

import pytest

from src.services import documents
from src.services.documents import DocumentAccessError, NoDocumentsConfigured

pytestmark = pytest.mark.asyncio


@pytest.fixture
def repo(tmp_path):
    # tmp repo:  docs/a.md, docs/sub/b.md, secret.md (NOT allowlisted), bin.dat (non-utf8)
    (tmp_path / "docs" / "sub").mkdir(parents=True)
    (tmp_path / "docs" / "a.md").write_text("alpha")
    (tmp_path / "docs" / "sub" / "b.md").write_text("bravo")
    (tmp_path / "readme.md").write_text("readme")
    (tmp_path / "secret.md").write_text("secret")
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _stub_project(monkeypatch, repo):
    # allowlist: the whole docs/ dir (recursive) + readme.md (single file). secret.md/bin.dat NOT listed.
    row = {"id": "p", "root_path": repo,
           "documents": [{"path": "docs/", "description": "docs dir"},
                         {"path": "readme.md", "description": "the readme"}]}

    async def _get(project_id):
        return row if project_id == "p" else None

    monkeypatch.setattr(documents.projects_repo, "get", _get)
    return row


# --- allowlist ---

async def test_read_allowed_file():
    out = await documents.read_documents("p", ["readme.md"])
    assert "===== FILE: readme.md =====" in out and "readme" in out


async def test_read_dir_is_recursive():
    out = await documents.read_documents("p", ["docs/"])
    assert "alpha" in out and "bravo" in out  # docs/a.md AND docs/sub/b.md


async def test_non_allowlisted_file_denied():
    with pytest.raises(DocumentAccessError):
        await documents.read_documents("p", ["secret.md"])


async def test_dotdot_escape_denied():
    with pytest.raises(DocumentAccessError):
        await documents.read_documents("p", ["docs/../secret.md"])


async def test_any_disallowed_rejects_whole_call():
    # one good + one bad path -> whole call fails, nothing read.
    with pytest.raises(DocumentAccessError):
        await documents.read_documents("p", ["readme.md", "secret.md"])


async def test_symlink_escape_denied(repo):
    # a symlink INSIDE docs/ pointing at secret.md must not grant access (realpath escapes the allowlist).
    link = os.path.join(repo, "docs", "leak.md")
    os.symlink(os.path.join(repo, "secret.md"), link)
    with pytest.raises(DocumentAccessError):
        await documents.read_documents("p", ["docs/leak.md"])


# --- read behavior ---

async def test_non_utf8_becomes_unreadable(monkeypatch, repo, _stub_project):
    _stub_project["documents"].append({"path": "bin.dat", "description": "binary"})
    out = await documents.read_documents("p", ["bin.dat"])
    assert "[unreadable: bin.dat]" in out


async def test_missing_file_errors():
    with pytest.raises(DocumentAccessError):
        # allowlisted-shaped but nonexistent (under docs/) -> not found
        await documents.read_documents("p", ["docs/nope.md"])


# --- list ---

async def test_list_directory_immediate_only():
    entries = await documents.list_directory("p", "docs/")
    names = {e["name"] for e in entries}
    assert names == {"a.md", "sub"}  # immediate children only, not sub/b.md
    assert {e["type"] for e in entries} == {"file", "dir"}


async def test_list_subdir_of_allowed_dir():
    entries = await documents.list_directory("p", "docs/sub")
    assert {e["name"] for e in entries} == {"b.md"}


async def test_list_non_allowed_denied():
    with pytest.raises(DocumentAccessError):
        await documents.list_directory("p", ".")  # repo root not allowlisted


# --- list_documents + no-config ---

async def test_list_documents_returns_catalog():
    docs = await documents.list_documents("p")
    assert [d["path"] for d in docs] == ["docs/", "readme.md"]


async def test_no_documents_configured(monkeypatch):
    async def _get(_):
        return {"id": "empty", "root_path": "/tmp"}
    monkeypatch.setattr(documents.projects_repo, "get", _get)
    assert await documents.list_documents("empty") == []
    with pytest.raises(NoDocumentsConfigured):
        await documents.read_documents("empty", ["x"])
