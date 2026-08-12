# Tests for _embed's batching -- endpoint texts fold in the full spread, so all-in-one-call blows voyage's
# 120k-token / 1000-doc per-batch caps (a real rebuild hit ~760k tokens and errored). _embed must chunk under
# both caps while preserving output order. The voyage client is mocked (no API calls).

from src.services import search


class _FakeVoyage:
    """Counts len(text) as 'tokens'; embed() returns a length-marker per text and records batch sizes."""
    def __init__(self):
        self.batch_sizes: list[int] = []

    def count_tokens(self, texts, model=None):
        return sum(len(t) for t in texts)

    def embed(self, texts, model=None):
        self.batch_sizes.append(len(texts))
        return type("R", (), {"embeddings": [[float(len(t))] for t in texts]})()


def _install(monkeypatch, max_tokens=100, max_docs=1000):
    fake = _FakeVoyage()
    monkeypatch.setattr(search, "_client", fake)
    monkeypatch.setattr(search, "_MAX_BATCH_TOKENS", max_tokens)
    monkeypatch.setattr(search, "_MAX_BATCH_DOCS", max_docs)
    return fake


def test_empty_returns_empty(monkeypatch):
    _install(monkeypatch)
    assert search._embed([]) == []


def test_splits_on_token_cap_and_preserves_order(monkeypatch):
    fake = _install(monkeypatch, max_tokens=100)
    texts = ["a" * 40, "b" * 40, "c" * 40, "d" * 10]  # 40+40 fit (80); +40 -> new batch
    out = search._embed(texts)
    assert [int(e[0]) for e in out] == [40, 40, 40, 10]  # order preserved
    assert fake.batch_sizes == [2, 2]
    # every multi-doc batch stayed under the cap
    assert all(sz == 1 or sz <= search._MAX_BATCH_DOCS for sz in fake.batch_sizes)


def test_oversized_single_doc_goes_alone_not_dropped(monkeypatch):
    fake = _install(monkeypatch, max_tokens=100)
    out = search._embed(["x" * 500, "y" * 10])  # first doc alone exceeds the cap
    assert [int(e[0]) for e in out] == [500, 10]  # both embedded, in order
    assert fake.batch_sizes == [1, 1]


def test_splits_on_doc_count_cap(monkeypatch):
    fake = _install(monkeypatch, max_tokens=10**9, max_docs=3)
    out = search._embed(["t"] * 7)
    assert len(out) == 7
    assert fake.batch_sizes == [3, 3, 1]
