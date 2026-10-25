from typing import cast

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.shared.kernel.contracts import AGENT_OUTPUT_VERSION
from src.shared.kernel.types import (
    AgentOutputArtifactPayload,
    AgentOutputKind,
    ArtifactReferencePayload,
    JSONObject,
)


class ArtifactReference(BaseModel):
    """Pointer to a large artifact stored by the artifact capability."""

    artifact_id: str = Field(..., description="UUID of the artifact in the store")
    download_url: str = Field(
        ...,
        description="API endpoint to fetch the artifact (e.g., /api/v1/artifacts/{id})",
    )
    type: str = Field(
        ...,
        description="Artifact type identifier (e.g., 'financial_report', 'news_analysis')",
    )


class AgentOutputArtifact(BaseModel):
    """Standard L1 summary, L2 preview, and L3 artifact reference container."""

    kind: AgentOutputKind = Field(..., description="Output contract kind discriminator")
    version: str = Field(
        default=AGENT_OUTPUT_VERSION,
        description="Output contract version. Must be 'v1'.",
    )
    summary: str = Field(..., description="L1: Short summary for message bubble")
    preview: dict[str, object] | None = Field(
        default=None, description="L2: Hot data for immediate UI rendering"
    )
    reference: ArtifactReference | None = Field(
        default=None, description="L3: Pointer to the Artifact Store"
    )

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> str:
        if value != AGENT_OUTPUT_VERSION:
            raise TypeError(f"Agent output version must be {AGENT_OUTPUT_VERSION!r}")
        return AGENT_OUTPUT_VERSION


def to_artifact_reference_payload(
    reference: ArtifactReference,
) -> ArtifactReferencePayload:
    return cast(ArtifactReferencePayload, reference.model_dump(mode="json"))


def to_artifact_payload(artifact: AgentOutputArtifact) -> AgentOutputArtifactPayload:
    return cast(AgentOutputArtifactPayload, artifact.model_dump(mode="json"))


def parse_agent_output_artifact_payload(
    value: object, context: str = "agent output artifact"
) -> AgentOutputArtifactPayload:
    try:
        model = AgentOutputArtifact.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc
    return cast(AgentOutputArtifactPayload, model.model_dump(mode="json"))


def build_artifact_payload(
    kind: AgentOutputKind,
    summary: str,
    preview: JSONObject | None,
    reference: ArtifactReference | None,
    version: str = AGENT_OUTPUT_VERSION,
) -> AgentOutputArtifactPayload:
    return to_artifact_payload(
        AgentOutputArtifact(
            kind=kind,
            version=version,
            summary=summary,
            preview=preview,
            reference=reference,
        )
    )
