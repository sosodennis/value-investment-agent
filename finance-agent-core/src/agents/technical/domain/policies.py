from __future__ import annotations

from .models import (
    SemanticConfluenceResult,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)


def assemble_semantic_tags(
    payload: SemanticTagPolicyInput,
) -> SemanticTagPolicyResult:
    tags: list[str] = []
    evidence_text: list[str] = []

    z_score = payload.z_score
    optimal_d = payload.optimal_d
    confluence = payload.confluence

    cdf_val = confluence.statistical_strength

    abs_z = abs(z_score)
    statistical_state = "equilibrium"
    risk_level = "low"

    if abs_z < 1.0:
        tags.append("MARKET_NOISE")
    elif 1.0 <= abs_z < 2.0:
        statistical_state = "deviating"
        risk_level = "medium"
        tags.append("TREND_ACTIVE")
    else:
        statistical_state = "anomaly"
        risk_level = "critical"
        tags.append("STATISTICAL_EXTREME")

    memory_strength = "balanced"
    if optimal_d < 0.3:
        memory_strength = "structurally_stable"
        tags.append("STRUCTURE_ROBUST")
    elif optimal_d > 0.6:
        memory_strength = "fragile"
        tags.append("STRUCTURE_FRAGILE")

    bollinger_state = confluence.bollinger_state
    macd_momentum = confluence.macd_momentum

    if (z_score > 2.0) and (bollinger_state == "BREAKOUT_UPPER"):
        tags.append("SETUP_PERFECT_STORM_SHORT")
        risk_level = "critical"
        evidence_text.append(
            f"CRITICAL: Statistical anomaly confirmed (Z={z_score:.1f}, Prob>{cdf_val:.1f}%) with volatility breakout."
        )
    elif (z_score < -2.0) and (bollinger_state == "BREAKOUT_LOWER"):
        tags.append("SETUP_PERFECT_STORM_LONG")
        risk_level = "critical"
        evidence_text.append(
            f"CRITICAL: Price structure implies imminent mean reversion (Z={z_score:.1f}, Prob<{cdf_val:.1f}%)."
        )
    elif (1.0 < z_score < 2.0) and (macd_momentum == "BULLISH_EXPANDING"):
        tags.append("SETUP_HEALTHY_MOMENTUM")
        evidence_text.append(
            f"Trend is supported by expanding memory momentum (Prob: {cdf_val:.1f}%) without statistical overheating."
        )
    elif 1.5 < z_score < 2.0:
        tags.append("WARNING_INTERNAL_PRESSURE")
        evidence_text.append(
            f"Internal structure is heating up (Prob: {cdf_val:.1f}%) approaching statistical limits."
        )
    elif -2.0 < z_score < -1.5:
        tags.append("WARNING_INTERNAL_WEAKNESS")
        evidence_text.append(
            f"Internal structure is weakening (Prob: {cdf_val:.1f}%) approaching statistical limits."
        )

    obv_z = confluence.obv_z
    obv_state = confluence.obv_state
    volume_price_tags: list[str] = []

    if (z_score > 0.5) and (obv_z > 0.5):
        volume_price_tags.append("VOLUME_CONFIRMED_UP")
        evidence_text.append(
            "Price rise is supported by strong volume accumulation (healthy trend)."
        )
    elif (z_score > 1.5) and (obv_z < -0.5):
        volume_price_tags.append("DIVERGENCE_PRICE_UP_VOL_DOWN")
        tags.append("SMART_MONEY_EXITING")
        evidence_text.append(
            "WARNING: Price is rising but FD-OBV indicates distribution (Smart Money Exit)."
        )
        if risk_level != "critical":
            risk_level = "medium"
    elif (z_score < -1.5) and (obv_z > 0.5):
        volume_price_tags.append("DIVERGENCE_PRICE_DOWN_VOL_UP")
        tags.append("SMART_MONEY_ENTERING")
        evidence_text.append(
            "OPPORTUNITY: Price is falling but FD-OBV indicates hidden accumulation."
        )
    elif (z_score < -2.0) and (obv_z < -2.0):
        tags.append("CAPITULATION_EVENT")
        evidence_text.append(
            "Market is undergoing a capitulation event (High volume sell-off)."
        )

    tags.extend(volume_price_tags)

    if z_score > 0.5:
        direction = "BULLISH_EXTENSION"
    elif z_score < -0.5:
        direction = "BEARISH_EXTENSION"
    else:
        direction = "NEUTRAL_CONSOLIDATION"

    if ("SMART_MONEY_EXITING" in tags) and ("SETUP_HEALTHY_MOMENTUM" in tags):
        tags.remove("SETUP_HEALTHY_MOMENTUM")
        tags.append("PATTERN_BULL_TRAP")
        evidence_text.append(
            "CRITICAL OVERRIDE: Price action suggests strength, but significant capital outflows verify this is a BULL TRAP."
        )
        risk_level = "critical"

    if ("SMART_MONEY_ENTERING" in tags) and (direction == "BEARISH_EXTENSION"):
        tags.append("PATTERN_BEAR_TRAP")
        evidence_text.append(
            "OPPORTUNITY OVERRIDE: Price weakness is not supported by volume; Smart money is absorbing the selling (Accumulation)."
        )
        if risk_level == "critical":
            risk_level = "medium"

    return SemanticTagPolicyResult(
        tags=tags,
        direction=direction,
        risk_level=risk_level,
        memory_strength=memory_strength,
        statistical_state=statistical_state,
        z_score=float(round(z_score, 2)),
        confluence=SemanticConfluenceResult(
            bollinger_state=bollinger_state,
            statistical_strength=float(round(cdf_val, 2)),
            macd_momentum=macd_momentum,
            obv_state=obv_state,
        ),
        evidence_list=evidence_text,
    )
