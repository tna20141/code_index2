# Intentions: semantic search over the curated entities, PER PROJECT. voyage-code-3 embeddings + a FAISS
# IndexFlatL2 on disk per (project, entity_type) (brute-force k-NN is instant at our scale). Full rebuild,
# manually triggered. Embedded text = curated meaning + light structural signal (spec section 6): endpoints
# also fold in their live spread (regenerated per build -- the index is a point-in-time snapshot). The
# resolver + root_path for that spread come from the project registry. References: docs/spec.md section 6.

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

_EMBED_MODEL = "voyage-code-3"
_DISTANCE_THRESHOLD = 1.0  # drop matches beyond this L2 distance (garbage-match cutoff)

_client: voyageai.Client | None = None


def _voyage() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def _embed(texts: list[str]) -> list[list[float]]:
    return _voyage().embed(texts, model=_EMBED_MODEL).embeddings


def _index_path(project_id: str, entity_type: str) -> str:
    # per-project subdir so projects' vectors never mix.
    return os.path.join(settings.faiss_index_dir, project_id, entity_type)


# --- embedded-text builders (curated meaning + associative id/ref slugs) ---

async def _endpoint_text(project_id: str, root_path: str, ep: dict) -> str:
    parts = [ep["id"], ep.get("description", ""), ep.get("annotation", ""), ep.get("trigger", "")]
    try:
        resolver = await project_registry.get_resolver(project_id)
        # resolve the handler (path:symbol -> current line via LSP) and fold in its live spread.
        definition, err = await reads.resolve_endpoint_start(resolver, project_id, root_path, ep["id"])
        if definition is not None and err is None:
            parts.append(await spread_svc.spread(
                project_id, root_path, resolver, definition, mode=SpreadMode.FLAT))
    except Exception:  # noqa: BLE001, S110 -- best-effort enrichment; any hiccup must not drop the endpoint
        pass
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
