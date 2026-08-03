# Unit tests for the spread leaf-classification rules (services/spread/boundary). Pure logic, no I/O.

from src.services.spread import boundary
from src.services.spread.lsp import Definition

_ROOT = "/home/x/repo"


def _def(path: str) -> Definition:
    return Definition(path=path, line=1, col=1)


def test_library_call_outside_repo_root():
    assert boundary.is_library_call(_def("/usr/lib/python3.12/json/__init__.py"), _ROOT) is True
    assert boundary.is_library_call(
        _def("/home/x/repo/.venv/lib/site-packages/pydash/__init__.py"), _ROOT) is True


def test_own_code_under_repo_root():
    assert boundary.is_library_call(_def("/home/x/repo/src/services/foo.py"), _ROOT) is False


def test_repo_frontier_by_path():
    assert boundary.is_repo_frontier(_def("/home/x/repo/src/repositories/campaigns.py")) is True
    assert boundary.is_repo_frontier(_def("/home/x/repo/src/modules/actions/repository.py")) is True
    assert boundary.is_repo_frontier(_def("/home/x/repo/src/services/foo.py")) is False


def test_trivial_marker_detected():
    assert boundary.is_trivial(["# ci:trivial", "def foo():"]) is True
    assert boundary.is_trivial(["    # ci:trivial", "@decorator"]) is True  # indented marker
    assert boundary.is_trivial(["# Intentions: not trivial", "def foo():"]) is False
    assert boundary.is_trivial([]) is False
