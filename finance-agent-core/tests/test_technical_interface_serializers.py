from __future__ import annotations

import pytest

from src.agents.technical.interface.contracts import parse_technical_artifact_model
from src.agents.technical.interface.serializers import (
    build_data_fetch_preview,
    build_fracdiff_progress_preview,
)


def test_build_data_fetch_preview_formats_price() -> None:
    preview = build_data_fetch_preview(ticker="GME", latest_price=23.456)
    assert preview["ticker"] == "GME"
    assert preview["latest_price_display"] == "$23.46"
    assert preview["signal_display"] == "📊 FETCHING DATA..."


def test_build_fracdiff_progress_preview_formats_metrics() -> None:
    preview = build_fracdiff_progress_preview(
        ticker="GME",
        latest_price=23.4,
        z_score=1.234,
        optimal_d=0.42,
        statistical_strength=70.2,
    )
    assert preview["latest_price_display"] == "$23.40"
    assert preview["z_score_display"] == "Z: +1.23"
    assert preview["optimal_d_display"] == "d=0.42"
    assert preview["strength_display"] == "Strength: 70.2"


def test_parse_technical_artifact_model_returns_json_dto() -> None:
    parsed = parse_technical_artifact_model(
        {
            "ticker": "GME",
            "timestamp": "2026-02-16T00:00:00Z",
            "frac_diff_metrics": {
                "optimal_d": 0.42,
                "window_length": 120,
                "adf_statistic": -3.2,
                "adf_pvalue": 0.03,
                "memory_strength": "balanced",
            },
            "signal_state": {
                "z_score": 1.2,
                "statistical_state": "deviating",
                "direction": "bullish",
                "risk_level": "medium",
                "confluence": {
                    "bollinger_state": "upper",
                    "macd_momentum": "up",
                    "obv_state": "accumulation",
                    "statistical_strength": 0.7,
                },
            },
            "semantic_tags": ["mean-reversion"],
            "llm_interpretation": "test",
        }
    )
    assert isinstance(parsed, dict)
    assert parsed["ticker"] == "GME"


def test_parse_technical_artifact_model_rejects_non_object() -> None:
    with pytest.raises(TypeError):
        parse_technical_artifact_model(["bad"])
