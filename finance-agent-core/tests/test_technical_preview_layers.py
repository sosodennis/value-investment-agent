from src.agents.technical.application.view_models import derive_ta_preview_view_model
from src.agents.technical.interface.formatters import format_ta_preview


def test_derive_ta_preview_view_model_computes_zscore_state() -> None:
    view_model = derive_ta_preview_view_model(
        {
            "ticker": "GME",
            "latest_price": 23.4,
            "signal": "BUY",
            "z_score_latest": 2.2,
            "optimal_d": 0.41,
            "statistical_strength": 71,
        }
    )
    assert view_model["ticker"] == "GME"
    assert view_model["z_score"] == 2.2
    assert view_model["z_score_state"] == "Anomaly"


def test_format_ta_preview_formats_display_fields() -> None:
    preview = format_ta_preview(
        {
            "ticker": "GME",
            "latest_price": 23.4,
            "signal": "BUY",
            "z_score": 1.23,
            "z_score_state": "Deviating",
            "optimal_d": 0.41,
            "strength": 71,
        }
    )
    assert preview["latest_price_display"] == "$23.40"
    assert preview["signal_display"] == "📈 BUY"
    assert preview["z_score_display"] == "Z: +1.23 (Deviating)"
    assert preview["optimal_d_display"] == "d=0.41"
