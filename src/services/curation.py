# Intentions: the write-side business logic behind the admin MCP -- create/update/delete for every curated
# entity, with (1) reference validation on write (reject dangling endpoint/label/artifact ids) and (2)
# cascade purge on delete ($pull the deleted id from every referencing array). All project-scoped: refs
# resolve WITHIN the project, cascades never cross projects. The repos own the raw Mongo ops; this layer
# decides WHICH validations run and WHICH cascades fire. References: docs/spec.md sections 4, 5.

from src.dto import Endpoint, Flow, Label, LogicArtifact, Subsystem
from src.repositories import (
    COLL_ENDPOINTS,
    COLL_FLOWS,
    COLL_LOGIC_ARTIFACTS,
    COLL_SUBSYSTEMS,
    endpoints,
    flows,
    index_meta,
    labels,
    logic_artifacts,
    subsystems,
)
from src.utils import mongo


class DanglingReferenceError(ValueError):
    """A create/update referenced ids that don't exist. Carries the missing ids; nothing was written."""


async def _validate_refs(project_id: str, label_names: list[str] | None, artifact_ids: list[str] | None,
                         endpoint_ids: list[str] | None) -> None:
    """Reject if any referenced label/artifact/endpoint is missing IN THIS PROJECT. All-or-nothing: we
    validate before any write, so a rejected call leaves the store untouched."""
    missing: list[str] = []
    if label_names:
        missing += [f"label:{n}" for n in await labels.find_missing(project_id, label_names)]
    if artifact_ids:
        missing += [f"logic_artifact:{i}" for i in await logic_artifacts.find_missing(project_id, artifact_ids)]
    if endpoint_ids:
        missing += [f"endpoint:{i}" for i in await endpoints.find_missing(project_id, endpoint_ids)]
    if missing:
        raise DanglingReferenceError(f"references do not exist: {', '.join(missing)}")


def _scope(project_id: str) -> dict:
    # [Pure] the project filter for cascade $pull (keeps a cascade from crossing projects).
    return {"project_id": project_id}


# --- Endpoint ---

async def create_endpoint(endpoint: Endpoint) -> str:
    await _validate_refs(endpoint["project_id"], endpoint.get("labels"), endpoint.get("logic_artifacts"), None)
    await endpoints.insert(endpoint)
    return endpoint["id"]


async def update_endpoint(project_id: str, endpoint_id: str, updates: dict) -> None:
    """Update any subset of an endpoint's fields. Validates label/artifact refs if present."""
    await _validate_refs(project_id, updates.get("labels"), updates.get("logic_artifacts"), None)
    await endpoints.update(project_id, endpoint_id, updates)


async def delete_endpoint(project_id: str, endpoint_id: str) -> None:
    """Delete + cascade: purge this endpoint id from every flow's endpoint_ids (in-project). Subsystems
    reference endpoints inline in `content` prose (no id array), so nothing to cascade there."""
    await endpoints.delete(project_id, endpoint_id)
    await mongo.pull_from_all(COLL_FLOWS, _scope(project_id), "endpoint_ids", endpoint_id)


# --- Flow ---

async def create_flow(flow: Flow) -> str:
    await _validate_refs(flow["project_id"], flow.get("labels"), flow.get("logic_artifacts"),
                         flow.get("endpoint_ids"))
    await flows.insert(flow)
    return flow["id"]


async def update_flow(project_id: str, flow_id: str, updates: dict) -> None:
    await _validate_refs(project_id, updates.get("labels"), updates.get("logic_artifacts"),
                         updates.get("endpoint_ids"))
    await flows.update(project_id, flow_id, updates)


async def delete_flow(project_id: str, flow_id: str) -> None:
    await flows.delete(project_id, flow_id)  # nothing references a flow by id (subsystems ref flows in prose)


# --- Subsystem ---

async def create_subsystem(subsystem: Subsystem) -> str:
    await _validate_refs(subsystem["project_id"], subsystem.get("labels"), subsystem.get("logic_artifacts"),
                         None)  # subsystems carry no endpoint_ids (refs are inline in content)
    await subsystems.insert(subsystem)
    return subsystem["id"]


async def update_subsystem(project_id: str, subsystem_id: str, updates: dict) -> None:
    await _validate_refs(project_id, updates.get("labels"), updates.get("logic_artifacts"), None)
    await subsystems.update(project_id, subsystem_id, updates)


async def delete_subsystem(project_id: str, subsystem_id: str) -> None:
    await subsystems.delete(project_id, subsystem_id)


# --- Logic artifact ---

async def create_logic_artifact(artifact: LogicArtifact) -> str:
    await _validate_refs(artifact["project_id"], artifact.get("labels"), None, None)
    await logic_artifacts.insert(artifact)
    return artifact["id"]


async def update_logic_artifact(project_id: str, artifact_id: str, updates: dict) -> None:
    await _validate_refs(project_id, updates.get("labels"), None, None)
    await logic_artifacts.update(project_id, artifact_id, updates)


async def delete_logic_artifact(project_id: str, artifact_id: str) -> None:
    """Delete + cascade: purge this artifact id from every entity's logic_artifacts array (in-project)."""
    await logic_artifacts.delete(project_id, artifact_id)
    for coll in (COLL_ENDPOINTS, COLL_FLOWS, COLL_SUBSYSTEMS):
        await mongo.pull_from_all(coll, _scope(project_id), "logic_artifacts", artifact_id)


# --- Label ---

async def create_label(label: Label) -> str:
    await labels.insert(label)
    return label["name"]


async def update_label(project_id: str, name: str, updates: dict) -> None:
    await labels.update(project_id, name, updates)


async def delete_label(project_id: str, name: str) -> None:
    """Delete + cascade: purge this label from every entity's labels array (in-project; endpoints/flows/
    subsystems/logic_artifacts all carry labels)."""
    await labels.delete(project_id, name)
    for coll in (COLL_ENDPOINTS, COLL_FLOWS, COLL_SUBSYSTEMS, COLL_LOGIC_ARTIFACTS):
        await mongo.pull_from_all(coll, _scope(project_id), "labels", name)


# --- Per-project watermark (thin passthrough to the repo; here so the MCP imports one service) ---

get_commit_hash = index_meta.get_commit_hash
set_commit_hash = index_meta.set_commit_hash
