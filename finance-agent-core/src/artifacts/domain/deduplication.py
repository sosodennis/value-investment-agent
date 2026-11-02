from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .envelope import ArtifactEnvelope


def artifact_content(
    value: ArtifactEnvelope | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(value, ArtifactEnvelope):
        return {
            "kind": value.kind,
            "version": value.version,
            "produced_by": value.produced_by,
            "data": value.data,
        }
    return {
        "kind": value.get("kind"),
        "version": value.get("version"),
        "produced_by": value.get("produced_by"),
        "data": value.get("data"),
    }


def artifact_dedupe_key(
    *,
    thread_id: str,
    source_run_id: str,
    produced_by: str,
    artifact_type: str,
    envelope: ArtifactEnvelope,
) -> str:
    content_hash = hashlib.sha256(
        json.dumps(
            artifact_content(envelope), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    identity = {
        "version": "workflow-artifact-v1",
        "thread_id": thread_id,
        "source_run_id": source_run_id,
        "produced_by": produced_by,
        "artifact_type": artifact_type,
        "payload_hash": content_hash,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def references_artifact(value: object, artifact_id: str) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "artifact_refs":
                if contains_string(nested, artifact_id):
                    return True
            elif key == "artifact_id" or key.endswith("_artifact_id"):
                if nested == artifact_id:
                    return True
            elif references_artifact(nested, artifact_id):
                return True
    elif isinstance(value, list):
        return any(references_artifact(item, artifact_id) for item in value)
    return False


def contains_string(value: object, target: str) -> bool:
    if isinstance(value, str):
        return value == target
    if isinstance(value, Mapping):
        return any(contains_string(item, target) for item in value.values())
    if isinstance(value, list):
        return any(contains_string(item, target) for item in value)
    return False
