from __future__ import annotations

from src.shared.kernel.types import JSONObject


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
