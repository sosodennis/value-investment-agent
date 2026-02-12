"""
Mappers for Technical Analysis agent.
Converts internal state/context to UI-friendly preview structures.
"""

from src.common.types import JSONObject


def summarize_ta_for_preview(ctx: JSONObject) -> JSONObject:
    """
    Summarize technical analysis results for UI preview.
    Target size < 1KB.
    """
    latest_price = ctx.get("latest_price")
    signal = ctx.get("signal")
    z_score = ctx.get("z_score_latest")
    optimal_d = ctx.get("optimal_d")
    strength = ctx.get("statistical_strength")

    # Format displays
    signal_emoji = {
        "BUY": "📈 BUY",
        "SELL": "📉 SELL",
        "HOLD": "⚖️ HOLD",
        "BULLISH_EXTENSION": "📈 BULLISH",
        "BEARISH_EXTENSION": "📉 BEARISH",
    }.get(str(signal).upper(), "❓ N/A")

    price_display = f"${latest_price:,.2f}" if latest_price is not None else "N/A"
    z_score_display = f"Z: {z_score:+.2f}" if z_score is not None else "Z: N/A"
    optimal_d_display = f"d={optimal_d:.2f}" if optimal_d is not None else "d=N/A"
    strength_display = (
        f"Strength: {strength}" if strength is not None else "Strength: N/A"
    )

    # Add interpretation to Z-score display if possible
    if z_score is not None:
        if abs(z_score) >= 2.0:
            z_score_display += " (Anomaly)"
        elif abs(z_score) >= 1.0:
            z_score_display += " (Deviating)"
        else:
            z_score_display += " (Equilibrium)"

    return {
        "ticker": ctx.get("ticker", "N/A"),
        "latest_price_display": price_display,
        "signal_display": signal_emoji,
        "z_score_display": z_score_display,
        "optimal_d_display": optimal_d_display,
        "strength_display": strength_display,
    }
