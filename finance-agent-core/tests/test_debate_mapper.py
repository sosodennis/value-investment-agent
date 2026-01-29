from src.workflow.nodes.debate.mappers import summarize_debate_for_preview


def test_summarize_debate_for_preview_full():
    ctx = {
        "final_verdict": "STRONG_LONG",
        "kelly_confidence": 0.85,
        "winning_thesis": "Growth continues to outperform expectations.",
        "primary_catalyst": "Next earnings call",
        "primary_risk": "Regulatory headwinds",
        "current_round": 3,
    }
    preview = summarize_debate_for_preview(ctx)

    assert preview["verdict_display"] == "📈 STRONG_LONG (85%)"
    assert preview["thesis_display"] == "Growth continues to outperform expectations."
    assert preview["catalyst_display"] == "Next earnings call"
    assert preview["risk_display"] == "Regulatory headwinds"
    assert "Completed 3 rounds" in preview["debate_rounds_display"]


def test_summarize_debate_for_preview_partial():
    ctx = {"final_verdict": "NEUTRAL", "current_round": 1}
    preview = summarize_debate_for_preview(ctx)

    assert "⚖️ NEUTRAL" in preview["verdict_display"]
    assert preview["thesis_display"] == "Analyzing investment thesis..."
    assert "Completed 1 rounds" in preview["debate_rounds_display"]


def test_summarize_debate_for_preview_empty():
    ctx = {}
    preview = summarize_debate_for_preview(ctx)

    assert "⚖️ NEUTRAL" in preview["verdict_display"]
    assert "Analyzing" in preview["thesis_display"]
