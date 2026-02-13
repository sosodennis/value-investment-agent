from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from src.common.contracts import ARTIFACT_CONTRACT_VERSION

ArtifactPayload = dict[str, object] | list[object]


class ArtifactEnvelope(BaseModel):
    kind: str
    version: str = ARTIFACT_CONTRACT_VERSION
    produced_by: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    data: ArtifactPayload

    @field_validator("kind", "version", "produced_by", mode="before")
    @classmethod
    def _non_empty_string(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TypeError("artifact envelope string fields must be non-empty strings")
        return value.strip()


def build_artifact_envelope(
    *,
    kind: str,
    produced_by: str,
    data: ArtifactPayload,
    version: str = ARTIFACT_CONTRACT_VERSION,
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        kind=kind,
        version=version,
        produced_by=produced_by,
        data=data,
    )


def parse_artifact_envelope(
    value: object, context: str = "artifact"
) -> ArtifactEnvelope:
    try:
        return ArtifactEnvelope.model_validate(value)
    except Exception as exc:
        raise TypeError(f"{context} is not a valid ArtifactEnvelope: {exc}") from exc


def parse_artifact_payload(
    value: object,
    *,
    context: str = "artifact",
    expected_kind: str | None = None,
    expected_version: str = ARTIFACT_CONTRACT_VERSION,
) -> ArtifactPayload:
    envelope = parse_artifact_envelope(value, context)
    if envelope.version != expected_version:
        raise TypeError(
            f"{context} has unsupported version {envelope.version!r}, expected {expected_version!r}"
        )
    if expected_kind is not None and envelope.kind != expected_kind:
        raise TypeError(
            f"{context} has kind {envelope.kind!r}, expected {expected_kind!r}"
        )
    return envelope.data
