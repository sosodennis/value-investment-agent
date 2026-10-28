from __future__ import annotations

from src.shared.kernel.types import JSONObject


def build_debate_success_update(
    *,
    conclusion_data: JSONObject,
    report_id: str | None,
    artifact: JSONObject | None,
) -> dict[str, object]:
    update: dict[str, object] = {
        "status": "success",
        "final_verdict": conclusion_data.get("decision")
        or conclusion_data.get("final_verdict"),
        "kelly_confidence": conclusion_data.get("kelly_confidence")
        if isinstance(conclusion_data.get("kelly_confidence"), int | float)
        else (
            float(conclusion_data["conviction"]) / 100
            if isinstance(conclusion_data.get("conviction"), int | float)
            else None
        ),
        "winning_thesis": conclusion_data.get("winning_thesis"),
        "primary_catalyst": conclusion_data.get("primary_catalyst"),
        "primary_risk": conclusion_data.get("primary_risk"),
        "report_id": report_id,
        "current_round": 3,
    }
    if artifact is not None:
        update["artifact"] = artifact
    return update
