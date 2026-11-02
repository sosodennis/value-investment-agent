"""Stable contracts and factories for artifact consumers."""

from typing import TypeVar

from pydantic import BaseModel

from src.artifacts.application.ports import ArtifactStoragePort
from src.artifacts.application.service import ArtifactService
from src.artifacts.application.typed_artifact_port import (
    TypedArtifactPort,
    TypedArtifactStore,
)
from src.artifacts.application.wiring import build_default_artifact_service
from src.artifacts.contracts.agent_output import (
    AGENT_OUTPUT_KINDS,
    AGENT_OUTPUT_VERSION,
    OUTPUT_KIND_DEBATE,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
    OUTPUT_KIND_GENERIC,
    OUTPUT_KIND_INTENT_EXTRACTION,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
    AgentOutputArtifact,
    AgentOutputArtifactPayload,
    AgentOutputKind,
    ArtifactReference,
    ArtifactReferencePayload,
    build_artifact_payload,
    parse_agent_output_artifact_payload,
    to_artifact_payload,
    to_artifact_reference_payload,
)
from src.artifacts.contracts.kinds import (
    ARTIFACT_KIND_DEBATE_FACTS,
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ARTICLE,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_NEWS_SELECTION,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_SEARCH_RESULTS,
    ARTIFACT_KIND_TA_ALERTS,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_DIRECTION_SCORECARD,
    ARTIFACT_KIND_TA_FEATURE_PACK,
    ARTIFACT_KIND_TA_FULL_REPORT,
    ARTIFACT_KIND_TA_FUSION_REPORT,
    ARTIFACT_KIND_TA_INDICATOR_SERIES,
    ARTIFACT_KIND_TA_PATTERN_PACK,
    ARTIFACT_KIND_TA_REGIME_PACK,
    ARTIFACT_KIND_TA_TIMESERIES_BUNDLE,
    ARTIFACT_KIND_TA_VERIFICATION_REPORT,
)
from src.artifacts.contracts.registry import (
    parse_artifact_data_json,
    parse_artifact_data_model_as,
)
from src.artifacts.contracts.version import ARTIFACT_CONTRACT_VERSION
from src.artifacts.domain.envelope import (
    ArtifactEnvelope,
    ArtifactPayload,
    build_artifact_envelope,
    parse_artifact_envelope,
    parse_artifact_payload,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def build_typed_artifact_port(
    *,
    kind: str,
    model: type[_ModelT],
    storage: ArtifactStoragePort | None = None,
) -> TypedArtifactPort[_ModelT]:
    if storage is None:
        storage = build_default_artifact_service()
    return TypedArtifactStore(storage=storage, kind=kind, model=model)


__all__ = [
    "AGENT_OUTPUT_KINDS",
    "AGENT_OUTPUT_VERSION",
    "ARTIFACT_CONTRACT_VERSION",
    "ARTIFACT_KIND_DEBATE_FACTS",
    "ARTIFACT_KIND_DEBATE_FINAL_REPORT",
    "ARTIFACT_KIND_FINANCIAL_REPORTS",
    "ARTIFACT_KIND_NEWS_ANALYSIS_REPORT",
    "ARTIFACT_KIND_NEWS_ARTICLE",
    "ARTIFACT_KIND_NEWS_ITEMS_LIST",
    "ARTIFACT_KIND_NEWS_SELECTION",
    "ARTIFACT_KIND_PRICE_SERIES",
    "ARTIFACT_KIND_SEARCH_RESULTS",
    "ARTIFACT_KIND_TA_ALERTS",
    "ARTIFACT_KIND_TA_CHART_DATA",
    "ARTIFACT_KIND_TA_DIRECTION_SCORECARD",
    "ARTIFACT_KIND_TA_FEATURE_PACK",
    "ARTIFACT_KIND_TA_FULL_REPORT",
    "ARTIFACT_KIND_TA_FUSION_REPORT",
    "ARTIFACT_KIND_TA_INDICATOR_SERIES",
    "ARTIFACT_KIND_TA_PATTERN_PACK",
    "ARTIFACT_KIND_TA_REGIME_PACK",
    "ARTIFACT_KIND_TA_TIMESERIES_BUNDLE",
    "ARTIFACT_KIND_TA_VERIFICATION_REPORT",
    "AgentOutputArtifact",
    "AgentOutputArtifactPayload",
    "AgentOutputKind",
    "ArtifactEnvelope",
    "ArtifactPayload",
    "ArtifactReference",
    "ArtifactReferencePayload",
    "ArtifactService",
    "ArtifactStoragePort",
    "OUTPUT_KIND_DEBATE",
    "OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH",
    "OUTPUT_KIND_FUNDAMENTAL_ANALYSIS",
    "OUTPUT_KIND_GENERIC",
    "OUTPUT_KIND_INTENT_EXTRACTION",
    "OUTPUT_KIND_TECHNICAL_ANALYSIS",
    "TypedArtifactPort",
    "TypedArtifactStore",
    "build_artifact_envelope",
    "build_artifact_payload",
    "build_default_artifact_service",
    "build_typed_artifact_port",
    "parse_agent_output_artifact_payload",
    "parse_artifact_data_json",
    "parse_artifact_data_model_as",
    "parse_artifact_envelope",
    "parse_artifact_payload",
    "to_artifact_payload",
    "to_artifact_reference_payload",
]
