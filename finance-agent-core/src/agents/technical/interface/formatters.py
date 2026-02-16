from __future__ import annotations

from src.shared.kernel.types import JSONObject


def format_ta_preview(view_model: JSONObject) -> JSONObject:
    signal = str(view_model.get("signal") or "").upper()
    signal_display = {
        "BUY": "📈 BUY",
        "SELL": "📉 SELL",
        "HOLD": "⚖️ HOLD",
        "BULLISH_EXTENSION": "📈 BULLISH",
        "BEARISH_EXTENSION": "📉 BEARISH",
    }.get(signal, "❓ N/A")

    latest_price = view_model.get("latest_price")
    z_score = view_model.get("z_score")
    optimal_d = view_model.get("optimal_d")
    strength = view_model.get("strength")
    z_score_state = str(view_model.get("z_score_state") or "N/A")

    price_display = (
        f"${float(latest_price):,.2f}"
        if isinstance(latest_price, int | float)
        else "N/A"
    )
    if isinstance(z_score, int | float):
        z_score_display = f"Z: {float(z_score):+.2f} ({z_score_state})"
    else:
        z_score_display = "Z: N/A"
    optimal_d_display = (
        f"d={float(optimal_d):.2f}" if isinstance(optimal_d, int | float) else "d=N/A"
    )
    strength_display = (
        f"Strength: {strength}" if strength is not None else "Strength: N/A"
    )

    return {
        "ticker": view_model.get("ticker", "N/A"),
        "latest_price_display": price_display,
        "signal_display": signal_display,
        "z_score_display": z_score_display,
        "optimal_d_display": optimal_d_display,
        "strength_display": strength_display,
    }
