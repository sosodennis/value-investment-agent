"""Admit signed model releases from a trusted deployment bundle."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .governance import ModelInventory, ModelReleaseEvidenceV1
from .policies import ModelSpecV1, dated_model_specs


class ModelReleaseDeploymentEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: ModelReleaseEvidenceV1
    artifact_files: dict[str, str]


class ModelReleaseDeploymentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["fundamental-model-release-deployment-v1"]
    releases: tuple[ModelReleaseDeploymentEntryV1, ...] = Field(min_length=1)


def load_model_release_deployment(
    path: Path,
    inventory: ModelInventory,
    *,
    at: datetime | None = None,
) -> tuple[ModelSpecV1, ...]:
    bundle = ModelReleaseDeploymentV1.model_validate_json(path.read_bytes())
    candidates = {
        (model.model_id, model.model_version): model for model in dated_model_specs()
    }
    base = path.resolve().parent
    admitted: list[ModelSpecV1] = []
    seen: set[tuple[str, str]] = set()
    for release in bundle.releases:
        evidence = release.evidence
        key = (evidence.model_id, evidence.model_version)
        if key not in candidates or key in seen:
            raise ValueError("model deployment requires a unique supported dated model")
        seen.add(key)
        expected_ids = {artifact.artifact_id for artifact in evidence.artifacts}
        if set(release.artifact_files) != expected_ids:
            raise ValueError(
                "model deployment must map every evidence artifact exactly"
            )
        payloads: dict[str, bytes] = {}
        for artifact_id, relative in release.artifact_files.items():
            file = Path(relative)
            resolved = (base / file).resolve()
            if file.is_absolute() or not resolved.is_relative_to(base):
                raise ValueError("model release artifact must stay within its bundle")
            payloads[artifact_id] = resolved.read_bytes()
        admitted.append(
            inventory.promote(candidates[key], evidence, artifact_bytes=payloads, at=at)
        )
    return tuple(admitted)
