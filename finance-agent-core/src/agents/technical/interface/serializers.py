from __future__ import annotations

from datetime import datetime

from src.agents.technical.domain.services import (
    derive_memory_strength,
    derive_statistical_state,
)
from src.common.types import JSONObject


def build_full_report_payload(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_dict: JSONObject,
    llm_interpretation: str,
    raw_data: JSONObject,
) -> JSONObject:
    bollinger = technical_context.get("bollinger")
    macd = technical_context.get("macd")
    obv = technical_context.get("obv")

    return {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "frac_diff_metrics": {
            "optimal_d": technical_context.get("optimal_d"),
            "window_length": technical_context.get("window_length"),
            "adf_statistic": technical_context.get("adf_statistic"),
            "adf_pvalue": technical_context.get("adf_pvalue"),
            "memory_strength": derive_memory_strength(
                technical_context.get("optimal_d")
            ),
        },
        "signal_state": {
            "z_score": technical_context.get("z_score_latest"),
            "statistical_state": derive_statistical_state(
                technical_context.get("z_score_latest")
            ),
            "direction": str(tags_dict.get("direction") or "NEUTRAL").upper(),
            "risk_level": str(tags_dict.get("risk_level") or "medium").lower(),
            "confluence": {
                "bollinger_state": (
                    bollinger.get("state", "INSIDE")
                    if isinstance(bollinger, dict)
                    else "INSIDE"
                ),
                "macd_momentum": (
                    macd.get("momentum_state", "NEUTRAL")
                    if isinstance(macd, dict)
                    else "NEUTRAL"
                ),
                "obv_state": (
                    obv.get("state", "NEUTRAL") if isinstance(obv, dict) else "NEUTRAL"
                ),
                "statistical_strength": technical_context.get(
                    "statistical_strength_val", 50.0
                ),
            },
        },
        "semantic_tags": tags_dict.get("tags", []),
        "llm_interpretation": llm_interpretation,
        "raw_data": raw_data,
    }
