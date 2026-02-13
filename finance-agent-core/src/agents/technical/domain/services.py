from __future__ import annotations

import math
from datetime import datetime

from src.common.types import JSONObject


def safe_float(value: object) -> float | None:
    try:
        numeric_value = float(value)
    except (ValueError, TypeError):
        return None

    if math.isnan(numeric_value) or math.isinf(numeric_value):
        return None
    return numeric_value


def derive_statistical_state(z_score: object) -> str:
    z_value = abs(safe_float(z_score) or 0.0)
    if z_value >= 2.0:
        return "anomaly"
    if z_value >= 1.0:
        return "deviating"
    return "equilibrium"


def derive_memory_strength(optimal_d: object) -> str:
    d_value = safe_float(optimal_d) or 0.5
    if d_value < 0.3:
        return "structurally_stable"
    if d_value > 0.6:
        return "fragile"
    return "balanced"


def build_full_report_payload(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_dict: JSONObject,
    llm_interpretation: str,
    raw_data: JSONObject,
) -> JSONObject:
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
                    technical_context.get("bollinger", {}).get("state", "INSIDE")
                    if isinstance(technical_context.get("bollinger"), dict)
                    else "INSIDE"
                ),
                "macd_momentum": (
                    technical_context.get("macd", {}).get("momentum_state", "NEUTRAL")
                    if isinstance(technical_context.get("macd"), dict)
                    else "NEUTRAL"
                ),
                "obv_state": (
                    technical_context.get("obv", {}).get("state", "NEUTRAL")
                    if isinstance(technical_context.get("obv"), dict)
                    else "NEUTRAL"
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
