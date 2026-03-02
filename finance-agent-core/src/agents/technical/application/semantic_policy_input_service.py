from __future__ import annotations

from src.agents.technical.domain.signal_policy import (
    SemanticConfluenceInput,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.shared.kernel.types import JSONObject


def build_semantic_policy_input(
    technical_context: JSONObject,
) -> SemanticTagPolicyInput:
    z_score_raw = technical_context.get("z_score_latest")
    optimal_d_raw = technical_context.get("optimal_d")
    z_score = float(z_score_raw) if isinstance(z_score_raw, int | float) else 0.0
    optimal_d = float(optimal_d_raw) if isinstance(optimal_d_raw, int | float) else 0.5

    bollinger_raw = technical_context.get("bollinger")
    bollinger_state = "INSIDE"
    if isinstance(bollinger_raw, dict):
        bollinger_state_raw = bollinger_raw.get("state")
        if isinstance(bollinger_state_raw, str) and bollinger_state_raw:
            bollinger_state = bollinger_state_raw

    macd_raw = technical_context.get("macd")
    macd_momentum = "NEUTRAL"
    if isinstance(macd_raw, dict):
        macd_momentum_raw = macd_raw.get("momentum_state")
        if isinstance(macd_momentum_raw, str) and macd_momentum_raw:
            macd_momentum = macd_momentum_raw

    obv_raw = technical_context.get("obv")
    obv_state = "NEUTRAL"
    obv_z = 0.0
    if isinstance(obv_raw, dict):
        obv_state_raw = obv_raw.get("state")
        if isinstance(obv_state_raw, str) and obv_state_raw:
            obv_state = obv_state_raw
        obv_z_raw = obv_raw.get("fd_obv_z")
        if isinstance(obv_z_raw, int | float):
            obv_z = float(obv_z_raw)

    statistical_strength_raw = technical_context.get("statistical_strength_val")
    statistical_strength = (
        float(statistical_strength_raw)
        if isinstance(statistical_strength_raw, int | float)
        else 50.0
    )

    return SemanticTagPolicyInput(
        z_score=z_score,
        optimal_d=optimal_d,
        confluence=SemanticConfluenceInput(
            bollinger_state=bollinger_state,
            statistical_strength=statistical_strength,
            macd_momentum=macd_momentum,
            obv_state=obv_state,
            obv_z=obv_z,
        ),
    )


def semantic_tags_to_dict(tags_result: SemanticTagPolicyResult) -> JSONObject:
    return {
        "tags": tags_result.tags,
        "direction": tags_result.direction,
        "risk_level": tags_result.risk_level,
        "memory_strength": tags_result.memory_strength,
        "statistical_state": tags_result.statistical_state,
        "z_score": tags_result.z_score,
        "confluence": {
            "bollinger_state": tags_result.confluence.bollinger_state,
            "statistical_strength": tags_result.confluence.statistical_strength,
            "macd_momentum": tags_result.confluence.macd_momentum,
            "obv_state": tags_result.confluence.obv_state,
        },
        "evidence_list": tags_result.evidence_list,
    }
