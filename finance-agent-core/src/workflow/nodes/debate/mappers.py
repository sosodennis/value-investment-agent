from src.common.types import JSONObject

from .schemas import DebatePreview


def summarize_debate_for_preview(ctx: JSONObject) -> JSONObject:
    """
    Maps DebateContext to DebatePreview.
    Ensures output is <1KB for rapid UI rendering.
    """
    verdict = ctx.get("final_verdict", "NEUTRAL")
    confidence = ctx.get("kelly_confidence")

    # Format verdict string
    icon = "📈" if "LONG" in str(verdict) else "📉" if "SHORT" in str(verdict) else "⚖️"
    confidence_str = f" ({confidence*100:.0f}%)" if confidence is not None else ""
    verdict_display = f"{icon} {verdict}{confidence_str}"

    return DebatePreview(
        verdict_display=verdict_display,
        thesis_display=ctx.get("winning_thesis") or "Analyzing investment thesis...",
        catalyst_display=ctx.get("primary_catalyst") or "Pending...",
        risk_display=ctx.get("primary_risk") or "Pending...",
        debate_rounds_display=f"Completed {ctx.get('current_round', 0)} rounds of adversarial debate",
    ).model_dump(mode="json")
