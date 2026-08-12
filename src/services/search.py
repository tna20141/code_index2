# Intentions: semantic search over the curated entities, PER PROJECT. voyage-code-3 embeddings + a FAISS
# IndexFlatL2 on disk per (project, entity_type) (brute-force k-NN is instant at our scale). Full rebuild,
# manually triggered. Embedded text = curated meaning + light structural signal (spec section 6): endpoints
# also fold in their live spread (regenerated per build -- the index is a point-in-time snapshot). The
# resolver + root_path for that spread come from the project registry. References: docs/spec.md section 6.

import asyncio
import logging
import os
import pickle

import faiss
import numpy as np
import voyageai

from src.config import settings
from src.constants import SEARCHABLE_ENTITY_TYPES, EntityType, SpreadMode
from src.repositories import endpoints, flows, logic_artifacts, subsystems
from src.services import project_registry, reads
from src.services import spread as spread_svc

_log = logging.getLogger("search")

_EMBED_MODEL = "voyage-code-3"
_DISTANCE_THRESHOLD = 1.0  # drop matches beyond this L2 distance (garbage-match cutoff)

_client: voyageai.Client | None = None


def _voyage() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


# voyage-code-3 accepts at most 120k tokens AND 1000 documents per embed() batch. Our endpoint texts fold in
# the full inlined spread, so all-endpoints-in-one-call easily blows the token cap (measured ~760k for 86
# endpoints). We chunk greedily under both limits. Use a margin below 120k because voyage counts per its own
# tokenizer and a lone doc near the ceiling would otherwise reject the whole batch.
_MAX_BATCH_TOKENS = 110_000
_MAX_BATCH_DOCS = 1000


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed `texts`, chunked so each embed() call stays under voyage's per-batch token + doc caps. Returns
    the embeddings in the SAME order as `texts` (batches are concatenated in order). A single text over the
    token cap goes in its own batch -- voyage truncates it server-side rather than rejecting (matches the
    'after truncation' wording in its own error)."""
    if not texts:
        return []
    client = _voyage()
    # Per-text token counts (voyage's own tokenizer -- LOCAL, no network; the budget matches what the API
    # enforces). The tokenizer file is downloaded + cached by the voyage SDK on first use.
    token_counts = [client.count_tokens([t], model=_EMBED_MODEL) for t in texts]

    embeddings: list[list[float]] = []
    batch: list[str] = []
    batch_tokens = 0

    def _flush() -> None:
        # One embed() API call for the accumulated batch. Logged so a caller watching stderr sees progress
        # (a rebuild embeds many batches of dense code and each call is a slow network round-trip).
        nonlocal batch, batch_tokens
        _log.info("embedding batch: %d docs, ~%d tokens", len(batch), batch_tokens)
        embeddings.extend(client.embed(batch, model=_EMBED_MODEL).embeddings)
        batch, batch_tokens = [], 0

    for text, n_tokens in zip(texts, token_counts):
        # Flush the current batch if adding this text would exceed either cap (and the batch isn't empty --
        # a single oversized text must still go through on its own, relying on voyage's truncation).
        if batch and (batch_tokens + n_tokens > _MAX_BATCH_TOKENS or len(batch) >= _MAX_BATCH_DOCS):
            _flush()
        batch.append(text)
        batch_tokens += n_tokens
    if batch:
        _flush()
    return embeddings


def _index_path(project_id: str, entity_type: str) -> str:
    # per-project subdir so projects' vectors never mix.
    return os.path.join(settings.faiss_index_dir, project_id, entity_type)


# --- embedded-text builders (curated meaning + associative id/ref slugs) ---

# Cap the spread-enrichment per endpoint. Folding the live spread in is best-effort flavor for the embedding,
# but it drags in the LSP resolver (jedi), whose startup/queries can be slow OR hang outright -- and a hang is
# NOT an exception, so a bare try/except can't save us; the whole rebuild would wedge on one endpoint. The
# timeout degrades a stuck/slow spread to metadata-only (id+description+annotation+trigger) for that endpoint.
_SPREAD_ENRICH_TIMEOUT_S = 30.0


async def _endpoint_text(project_id: str, root_path: str, ep: dict) -> str:
    parts = [ep["id"], ep.get("description", ""), ep.get("annotation", ""), ep.get("trigger", "")]
    try:
        async with asyncio.timeout(_SPREAD_ENRICH_TIMEOUT_S):
            resolver = await project_registry.get_resolver(project_id)
            # resolve the handler (path:symbol -> current line via LSP) and fold in its live spread.
            definition, err = await reads.resolve_endpoint_start(resolver, project_id, root_path, ep["id"])
            if definition is not None and err is None:
                parts.append(await spread_svc.spread(
                    project_id, root_path, resolver, definition, mode=SpreadMode.FLAT))
    except (Exception, TimeoutError):  # noqa: BLE001 -- best-effort; hang/hiccup must not drop the endpoint
        _log.warning("spread enrichment skipped for %s (slow/failed LSP)", ep["id"])
    return "\n".join(p for p in parts if p)


def _flow_text(flow: dict) -> str:
    return "\n".join([flow["id"], flow.get("description", ""), *flow.get("endpoint_ids", [])])


def _subsystem_text(sub: dict) -> str:
    return "\n".join([sub["id"], sub.get("description", ""), sub.get("content", "")])


def _artifact_text(art: dict) -> str:
    return "\n".join([art["id"], art.get("description", "")])


async def _collect(project_id: str, root_path: str, entity_type: EntityType) -> list[tuple[str, str]]:
    """(id, embedded_text) for every entity of a searchable type in this project."""
    if entity_type == EntityType.ENDPOINT:
        return [(e["id"], await _endpoint_text(project_id, root_path, e))
                for e in await endpoints.find(project_id, {})]
    if entity_type == EntityType.FLOW:
        return [(f["id"], _flow_text(f)) for f in await flows.find(project_id, {})]
    if entity_type == EntityType.SUBSYSTEM:
        return [(s["id"], _subsystem_text(s)) for s in await subsystems.find(project_id, {})]
    if entity_type == EntityType.LOGIC_ARTIFACT:
        return [(a["id"], _artifact_text(a)) for a in await logic_artifacts.find(project_id, {})]
    return []


async def rebuild_index(project_id: str, root_path: str, entity_type: EntityType) -> int:
    """Full rebuild of one type's FAISS index for this project. Returns the count indexed."""
    items = await _collect(project_id, root_path, entity_type)
    path = _index_path(project_id, entity_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    index = faiss.IndexFlatL2(1024)  # voyage-code-3 dimension
    ids = [i for i, _ in items]
    if items:
        vectors = np.array(_embed([t for _, t in items]), dtype="float32")
        index.add(vectors)
    faiss.write_index(index, path + ".index")
    # Blocking file write is fine: rebuild is a rare, manually-triggered admin op, not a hot path.
    with open(path + ".map", "wb") as f:  # noqa: ASYNC230
        pickle.dump(ids, f)
    return len(ids)


async def rebuild_all(project_id: str, root_path: str) -> dict[str, int]:
    """Rebuild every searchable type for this project. The manual build trigger."""
    return {t.value: await rebuild_index(project_id, root_path, t) for t in SEARCHABLE_ENTITY_TYPES}


def _search_one(project_id: str, entity_type: str, query_vec: np.ndarray, top_k: int) -> list[dict]:
    path = _index_path(project_id, entity_type)
    if not os.path.exists(path + ".index"):
        return []  # never built for this (project, type) -> skip, don't error
    index = faiss.read_index(path + ".index")
    with open(path + ".map", "rb") as f:
        ids = pickle.load(f)
    if index.ntotal == 0:
        return []
    distances, indices = index.search(query_vec, min(top_k, index.ntotal))
    return [
        {"id": ids[idx], "entity_type": entity_type, "score": float(dist)}
        for dist, idx in zip(distances[0], indices[0], strict=False)
        if 0 <= idx < len(ids) and dist <= _DISTANCE_THRESHOLD
    ]


async def search(project_id: str, query: str, entity_types: list[str] | None = None,
                 top_k: int = 20) -> list[dict]:
    """Semantic search across the requested types in `project_id` (default: all searchable). Returns ranked
    [{id, entity_type, score}] (lower score = closer). Voyage failure raises -- search can't proceed."""
    types = entity_types or [t.value for t in SEARCHABLE_ENTITY_TYPES]
    query_vec = np.array(_embed([query]), dtype="float32")
    hits = [h for t in types for h in _search_one(project_id, t, query_vec, top_k)]
    return sorted(hits, key=lambda h: h["score"])[:top_k]
