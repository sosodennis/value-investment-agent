"""Stable public contracts and services for technical signal fusion."""

from .application.fusion_runtime_service import (
    DirectionScorecard,
    FusionRuntimeRequest,
    FusionRuntimeResult,
    FusionRuntimeService,
    IndicatorContribution,
    ScorecardFrame,
)
from .domain.contracts import (
    SemanticConfluenceInput,
    SemanticConfluenceResult,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from .domain.policy_service import assemble_semantic_tags
from .domain.state_service import (
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)

__all__ = [
    "DirectionScorecard",
    "FusionRuntimeRequest",
    "FusionRuntimeResult",
    "FusionRuntimeService",
    "IndicatorContribution",
    "ScorecardFrame",
    "SemanticConfluenceInput",
    "SemanticConfluenceResult",
    "SemanticTagPolicyInput",
    "SemanticTagPolicyResult",
    "assemble_semantic_tags",
    "derive_memory_strength",
    "derive_statistical_state",
    "safe_float",
]
