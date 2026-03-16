"""signal_fusion subdomain facade."""

from .application import (
    FUSION_SCORECARD_MODEL_VERSION,
    DirectionScorecard,
    FusionRuntimeRequest,
    FusionRuntimeResult,
    FusionRuntimeService,
    IndicatorContribution,
    ScorecardFrame,
)
from .domain import (
    SemanticConfluenceInput,
    SemanticConfluenceResult,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
    assemble_semantic_tags,
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)

__all__ = [
    "DirectionScorecard",
    "FUSION_SCORECARD_MODEL_VERSION",
    "IndicatorContribution",
    "ScorecardFrame",
    "FusionRuntimeRequest",
    "FusionRuntimeResult",
    "FusionRuntimeService",
    "SemanticConfluenceInput",
    "SemanticConfluenceResult",
    "SemanticTagPolicyInput",
    "SemanticTagPolicyResult",
    "assemble_semantic_tags",
    "derive_memory_strength",
    "derive_statistical_state",
    "safe_float",
]
