"""signal_fusion subdomain facade."""

from .application import (
    FusionRuntimeRequest,
    FusionRuntimeResult,
    FusionRuntimeService,
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
