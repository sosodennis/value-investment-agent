from __future__ import annotations

from dataclasses import dataclass

from .envelope import ArtifactEnvelope


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    key: str | None
    thread_id: str | None
    kind: str
    envelope: ArtifactEnvelope
    dedupe_key: str | None
