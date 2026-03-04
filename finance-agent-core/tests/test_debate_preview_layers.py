from src.agents.debate.interface.formatters import format_debate_preview
from src.agents.debate.interface.preview_projection_service import (
    project_debate_preview,
)


def test_project_debate_preview_extracts_fields() -> None:
    view_model = project_debate_preview(
        {
            "final_verdict": "STRONG_LONG",
            "kelly_confidence": 0.85,
            "winning_thesis": "Growth continues",
            "primary_catalyst": "Earnings",
            "primary_risk": "Regulation",
            "current_round": 3,
        }
    )
    assert view_model["verdict"] == "STRONG_LONG"
    assert view_model["confidence"] == 0.85
    assert view_model["current_round"] == 3


def test_format_debate_preview_builds_display_strings() -> None:
    preview = format_debate_preview(
        {
            "verdict": "STRONG_LONG",
            "confidence": 0.85,
            "winning_thesis": "Growth continues",
            "primary_catalyst": "Earnings",
            "primary_risk": "Regulation",
            "current_round": 3,
        }
    )
    assert preview["verdict_display"] == "📈 STRONG_LONG (85%)"
    assert preview["thesis_display"] == "Growth continues"
    assert preview["catalyst_display"] == "Earnings"
    assert preview["risk_display"] == "Regulation"
    assert "Completed 3 rounds" in preview["debate_rounds_display"]
