from typing import Final, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, ValidationError, field_validator
from typing_extensions import TypedDict

from src.shared.kernel.types import JSONObject

AGENT_OUTPUT_VERSION: Final = "v1"
OUTPUT_KIND_INTENT_EXTRACTION: Final = "intent_extraction.output"
OUTPUT_KIND_FUNDAMENTAL_ANALYSIS: Final = "fundamental_analysis.output"
OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH: Final = "financial_news_research.output"
OUTPUT_KIND_DEBATE: Final = "debate.output"
OUTPUT_KIND_TECHNICAL_ANALYSIS: Final = "technical_analysis.output"
OUTPUT_KIND_GENERIC: Final = "generic.output"
AGENT_OUTPUT_KINDS: Final[tuple[str, ...]] = (
    OUTPUT_KIND_INTENT_EXTRACTION,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
    OUTPUT_KIND_DEBATE,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
    OUTPUT_KIND_GENERIC,
)
AgentOutputKind: TypeAlias = Literal[
    "intent_extraction.output",
    "fundamental_analysis.output",
    "financial_news_research.output",
    "debate.output",
    "technical_analysis.output",
    "generic.output",
]


class ArtifactReferencePayload(TypedDict):
    artifact_id: str
    download_url: str
    type: str


class AgentOutputArtifactPayload(TypedDict):
    kind: AgentOutputKind
    version: Literal["v1"]
    summary: str
    preview: JSONObject | None
    reference: ArtifactReferencePayload | None


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
