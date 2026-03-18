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
            "schema_version": "2.0",
            "ticker": "GME",
            "as_of": "2026-02-16T00:00:00Z",
            "direction": "BULLISH_EXTENSION",
            "risk_level": "medium",
            "artifact_refs": {},
            "summary_tags": ["mean-reversion"],
            "regime_summary": {
                "dominant_regime": "BULL_TREND",
                "timeframe_count": 1,
                "average_confidence": 0.73,
            },
            "volume_profile_summary": {"level_count": 2},
            "structure_confluence_summary": {
                "confluence_state": "strong",
                "confluence_score": 0.74,
                "reasons": ["near_volume_node"],
            },
            "evidence_bundle": {
                "primary_timeframe": "1d",
                "support_levels": [101.5, 99.0],
                "resistance_levels": [108.0],
                "breakout_signals": [
                    {"name": "BREAKOUT_UP", "confidence": 0.71},
                ],
                "scorecard_summary": {
                    "timeframe": "1d",
                    "overall_score": 0.64,
                },
                "conflict_reasons": ["1d:quant_neutral"],
            },
            "quality_summary": {
                "is_degraded": True,
                "degraded_reasons": ["1wk_QUANT_SKIPPED"],
                "overall_quality": "medium",
                "ready_timeframes": ["1d"],
                "degraded_timeframes": ["1wk"],
                "regime_inputs_ready_timeframes": ["1d"],
                "unavailable_indicator_count": 1,
                "alert_quality_gate_counts": {"passed": 1},
                "primary_timeframe": "1d",
            },
            "alert_readout": {
                "total_alerts": 2,
                "policy_count": 2,
                "highest_severity": "warning",
                "active_alert_count": 1,
                "monitoring_alert_count": 1,
                "suppressed_alert_count": 0,
                "quality_gate_counts": {"passed": 1, "degraded": 1},
                "top_alerts": [
                    {
                        "code": "RSI_OVERSOLD",
                        "title": "RSI oversold near support",
                        "severity": "warning",
                        "timeframe": "1d",
                        "policy_code": "TA_RSI_SUPPORT_REBOUND",
                        "lifecycle_state": "active",
                    }
                ],
            },
            "observability_summary": {
                "primary_timeframe": "1d",
                "observed_timeframes": ["1d"],
                "loaded_artifacts": [
                    "feature_pack",
                    "pattern_pack",
                    "regime_pack",
                    "fusion_report",
                    "alerts",
                ],
                "missing_artifacts": ["direction_scorecard"],
                "degraded_artifacts": ["feature_pack", "fusion_report", "alerts"],
                "loaded_artifact_count": 5,
                "missing_artifact_count": 1,
                "degraded_reason_count": 2,
            },
        }
    )
    assert isinstance(parsed, dict)
    assert parsed["ticker"] == "GME"
    assert parsed["regime_summary"]["dominant_regime"] == "BULL_TREND"
    assert parsed["structure_confluence_summary"]["confluence_score"] == 0.74
    assert parsed["evidence_bundle"]["primary_timeframe"] == "1d"
    assert parsed["evidence_bundle"]["breakout_signals"][0]["name"] == "BREAKOUT_UP"
    assert parsed["quality_summary"]["overall_quality"] == "medium"
    assert (
        parsed["alert_readout"]["top_alerts"][0]["policy_code"]
        == "TA_RSI_SUPPORT_REBOUND"
    )
    assert parsed["observability_summary"]["loaded_artifact_count"] == 5
    assert parsed["observability_summary"]["degraded_artifacts"] == [
        "feature_pack",
        "fusion_report",
        "alerts",
    ]


def test_parse_technical_artifact_model_rejects_non_object() -> None:
    with pytest.raises(TypeError):
        parse_technical_artifact_model(["bad"])
