from __future__ import annotations

from src.agents.debate.interface.formatters import format_debate_preview
from src.shared.kernel.types import JSONObject


def project_debate_preview(ctx: JSONObject) -> JSONObject:
    verdict = str(ctx.get("final_verdict", "NEUTRAL"))
    confidence_raw = ctx.get("kelly_confidence")
    confidence = (
        float(confidence_raw) if isinstance(confidence_raw, int | float) else None
    )

    return {
        "verdict": verdict,
        "confidence": confidence,
        "winning_thesis": str(
            ctx.get("winning_thesis") or "Analyzing investment thesis..."
        ),
        "primary_catalyst": str(ctx.get("primary_catalyst") or "Pending..."),
        "primary_risk": str(ctx.get("primary_risk") or "Pending..."),
        "current_round": int(ctx.get("current_round", 0) or 0),
    }


def summarize_debate_for_preview(ctx: JSONObject) -> JSONObject:
    view_model = project_debate_preview(ctx)
    return format_debate_preview(view_model)
