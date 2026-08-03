# Unit tests for the project registry -- DB-backed lazy resolver + the unusable-project errors. The resolver
# is stubbed (no real LSP) and projects_repo.get is stubbed (no DB needed).

import pytest

from src.services import project_registry
from src.services.project_registry import ProjectRootMissing, UnknownProject

pytestmark = pytest.mark.asyncio


class _StubResolver:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    project_registry._resolvers.clear()
    made = []

    def _make(root_path):
        r = _StubResolver()
        made.append((root_path, r))
        return r

    monkeypatch.setattr(project_registry, "make_resolver", _make)
    return made


def _stub_project(monkeypatch, tmp_path, root_path=None):
    # projects_repo.get returns a row with root_path (default: an existing dir).
    row = {"id": "p", "root_path": root_path if root_path is not None else str(tmp_path)}

    async def _get(project_id):
        return row if project_id == "p" else None

    monkeypatch.setattr(project_registry.projects_repo, "get", _get)


async def test_unknown_project_raises(monkeypatch):
    async def _none(_):
        return None
    monkeypatch.setattr(project_registry.projects_repo, "get", _none)
    with pytest.raises(UnknownProject):
        await project_registry.get_root("nope")


async def test_root_missing_on_disk_raises(monkeypatch, tmp_path):
    _stub_project(monkeypatch, tmp_path, root_path=str(tmp_path / "does-not-exist"))
    with pytest.raises(ProjectRootMissing):
        await project_registry.get_root("p")


async def test_get_root_returns_realpath(monkeypatch, tmp_path):
    _stub_project(monkeypatch, tmp_path)
    assert await project_registry.get_root("p") == str(tmp_path)


async def test_resolver_started_lazily_and_reused(monkeypatch, tmp_path, _isolate):
    _stub_project(monkeypatch, tmp_path)
    r1 = await project_registry.get_resolver("p")
    assert r1.started is True
    assert len(_isolate) == 1
    r2 = await project_registry.get_resolver("p")   # reuse, no second resolver
    assert r2 is r1
    assert len(_isolate) == 1


async def test_stop_all_tears_down(monkeypatch, tmp_path, _isolate):
    _stub_project(monkeypatch, tmp_path)
    r = await project_registry.get_resolver("p")
    await project_registry.stop_all()
    assert r.stopped is True
    assert not project_registry._resolvers
