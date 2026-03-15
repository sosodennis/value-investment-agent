"""signal_fusion.domain package."""

from .contracts import (
    SemanticConfluenceInput,
    SemanticConfluenceResult,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from .policy_service import assemble_semantic_tags
from .state_service import (
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)

__all__ = [
    "SemanticConfluenceInput",
    "SemanticConfluenceResult",
    "SemanticTagPolicyInput",
    "SemanticTagPolicyResult",
    "assemble_semantic_tags",
    "derive_memory_strength",
    "derive_statistical_state",
    "safe_float",
]
