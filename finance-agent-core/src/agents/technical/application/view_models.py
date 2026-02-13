from __future__ import annotations

from src.agents.technical.domain.services import safe_float
from src.common.types import JSONObject


def build_fracdiff_preview(
    *,
    ticker: str,
    latest_price: object,
    z_score: object,
    optimal_d: object,
    statistical_strength: object,
) -> JSONObject:
    latest_price_num = safe_float(latest_price) or 0.0
    z_score_num = safe_float(z_score) or 0.0
    optimal_d_num = safe_float(optimal_d) or 0.0
    strength_num = safe_float(statistical_strength) or 0.0

    return {
        "ticker": ticker,
        "latest_price_display": f"${latest_price_num:,.2f}",
        "signal_display": "🧬 COMPUTING...",
        "z_score_display": f"Z: {z_score_num:+.2f}",
        "optimal_d_display": f"d={optimal_d_num:.2f}",
        "strength_display": f"Strength: {strength_num:.1f}",
    }


def derive_ta_preview_view_model(ctx: JSONObject) -> JSONObject:
    z_score = ctx.get("z_score_latest")
    z_score_num = float(z_score) if isinstance(z_score, int | float) else None

    z_score_state = "N/A"
    if z_score_num is not None:
        if abs(z_score_num) >= 2.0:
            z_score_state = "Anomaly"
        elif abs(z_score_num) >= 1.0:
            z_score_state = "Deviating"
        else:
            z_score_state = "Equilibrium"

    return {
        "ticker": ctx.get("ticker", "N/A"),
        "latest_price": ctx.get("latest_price"),
        "signal": ctx.get("signal"),
        "z_score": z_score_num,
        "z_score_state": z_score_state,
        "optimal_d": ctx.get("optimal_d"),
        "strength": ctx.get("statistical_strength"),
    }
