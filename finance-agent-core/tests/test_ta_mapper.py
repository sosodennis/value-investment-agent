from src.workflow.nodes.technical_analysis.mappers import summarize_ta_for_preview


def test_summarize_ta_for_preview_full():
    ctx = {
        "latest_price": 245.67,
        "signal": "BUY",
        "z_score_latest": 2.1,
        "optimal_d": 0.42,
        "statistical_strength": "High",
    }
    preview = summarize_ta_for_preview(ctx)

    assert preview["latest_price_display"] == "$245.67"
    assert preview["signal_display"] == "📈 BUY"
    assert "Z: +2.10" in preview["z_score_display"]
    assert "Anomaly" in preview["z_score_display"]
    assert preview["optimal_d_display"] == "d=0.42"
    assert preview["strength_display"] == "Strength: High"


def test_summarize_ta_for_preview_empty():
    ctx = {}
    preview = summarize_ta_for_preview(ctx)

    assert preview["latest_price_display"] == "N/A"
    assert preview["signal_display"] == "❓ N/A"
    assert preview["z_score_display"] == "Z: N/A"
    assert preview["optimal_d_display"] == "d=N/A"
    assert preview["strength_display"] == "Strength: N/A"


def test_summarize_ta_for_preview_bullish_extension():
    ctx = {
        "latest_price": 100.0,
        "signal": "BULLISH_EXTENSION",
        "z_score_latest": 1.5,
        "optimal_d": 0.3,
        "statistical_strength": "Medium",
    }
    preview = summarize_ta_for_preview(ctx)

    assert preview["signal_display"] == "📈 BULLISH"
    assert "Deviating" in preview["z_score_display"]


def test_summarize_ta_for_preview_equilibrium():
    ctx = {"z_score_latest": 0.5}
    preview = summarize_ta_for_preview(ctx)
    assert "Equilibrium" in preview["z_score_display"]
