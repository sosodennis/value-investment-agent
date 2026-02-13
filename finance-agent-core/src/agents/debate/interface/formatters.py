from __future__ import annotations

from src.common.types import JSONObject


def format_debate_preview(view_model: JSONObject) -> JSONObject:
    verdict = str(view_model.get("verdict", "NEUTRAL"))
    confidence = view_model.get("confidence")

    icon = "📈" if "LONG" in verdict else "📉" if "SHORT" in verdict else "⚖️"
    confidence_str = (
        f" ({float(confidence) * 100:.0f}%)"
        if isinstance(confidence, int | float)
        else ""
    )
    verdict_display = f"{icon} {verdict}{confidence_str}"

    return {
        "verdict_display": verdict_display,
        "thesis_display": str(
            view_model.get("winning_thesis") or "Analyzing investment thesis..."
        ),
        "catalyst_display": str(view_model.get("primary_catalyst") or "Pending..."),
        "risk_display": str(view_model.get("primary_risk") or "Pending..."),
        "debate_rounds_display": f"Completed {int(view_model.get('current_round', 0) or 0)} rounds of adversarial debate",
    }
