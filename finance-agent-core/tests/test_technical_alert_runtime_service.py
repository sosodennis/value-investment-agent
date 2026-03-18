from __future__ import annotations

from src.agents.technical.subdomains.alerts import (
    AlertRuntimeRequest,
    AlertRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalIndicatorSeriesArtifactData,
    TechnicalIndicatorSeriesFrameData,
    TechnicalIndicatorSeriesFrameMetadataData,
    TechnicalPatternFlagData,
    TechnicalPatternFrameData,
    TechnicalPatternPackArtifactData,
)


def test_alert_runtime_emits_policy_metadata_for_existing_alerts() -> None:
    service = AlertRuntimeService()
    indicator_series = TechnicalIndicatorSeriesArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalIndicatorSeriesFrameData(
                timeframe="1d",
                start="2026-03-01T00:00:00Z",
                end="2026-03-18T00:00:00Z",
                series={
                    "RSI_14": {"2026-03-18T00:00:00Z": 72.4},
                    "FD_ZSCORE": {"2026-03-18T00:00:00Z": -2.3},
                },
                metadata=TechnicalIndicatorSeriesFrameMetadataData(
                    source_points=120,
                    max_points=120,
                    downsample_step=1,
                    sample_readiness="ready",
                    fidelity="high",
                    quality_flags=[],
                ),
            )
        },
    )
    pattern_pack = TechnicalPatternPackArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalPatternFrameData(
                support_levels=[],
                resistance_levels=[],
                volume_profile_levels=[],
                breakouts=[
                    TechnicalPatternFlagData(
                        name="BREAKOUT_UP",
                        confidence=0.82,
                        notes="Daily continuation breakout",
                    )
                ],
                trendlines=[],
                pattern_flags=[],
                confidence_scores={},
            )
        },
    )

    result = service.compute(
        AlertRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-18T00:00:00Z",
            indicator_series=indicator_series,
            pattern_pack=pattern_pack,
        )
    )

    assert len(result.alerts) == 3
    rsi_alert = next(alert for alert in result.alerts if alert.code == "RSI_OVERBOUGHT")
    fd_alert = next(alert for alert in result.alerts if alert.code == "FD_ZSCORE_LOW")
    breakout_alert = next(alert for alert in result.alerts if alert.code == "BREAKOUT")

    assert rsi_alert.policy is not None
    assert rsi_alert.policy.policy_code == "TA_RSI_14_EXTREME"
    assert rsi_alert.policy.lifecycle_state == "active"
    assert rsi_alert.policy.quality_gate == "pass"
    assert rsi_alert.policy.evidence_refs[0].signal_key == "RSI_14"
    assert "actual=72.40" in (rsi_alert.policy.trigger_reason or "")

    assert fd_alert.policy is not None
    assert fd_alert.policy.policy_code == "TA_FD_ZSCORE_EXTREME"
    assert fd_alert.policy.evidence_refs[0].artifact_kind == "ta_indicator_series"

    assert breakout_alert.policy is not None
    assert breakout_alert.policy.policy_code == "TA_BREAKOUT_CONFIDENCE"
    assert breakout_alert.policy.evidence_refs[0].signal_key == "BREAKOUT_UP"

    assert result.summary.total == 3
    assert result.summary.policy_count == 3
    assert result.summary.lifecycle_counts["active"] == 3
    assert result.summary.quality_gate_counts["pass"] == 3


def test_alert_runtime_marks_indicator_alerts_degraded_when_series_not_ready() -> None:
    service = AlertRuntimeService()
    indicator_series = TechnicalIndicatorSeriesArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalIndicatorSeriesFrameData(
                timeframe="1d",
                start="2026-03-01T00:00:00Z",
                end="2026-03-18T00:00:00Z",
                series={"RSI_14": {"2026-03-18T00:00:00Z": 28.0}},
                metadata=TechnicalIndicatorSeriesFrameMetadataData(
                    source_points=8,
                    max_points=120,
                    downsample_step=1,
                    sample_readiness="partial",
                    fidelity="low",
                    quality_flags=["SHORT_HISTORY"],
                ),
            )
        },
    )

    result = service.compute(
        AlertRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-18T00:00:00Z",
            indicator_series=indicator_series,
            pattern_pack=None,
        )
    )

    assert len(result.alerts) == 2
    oversold_alert = next(
        alert for alert in result.alerts if alert.code == "RSI_OVERSOLD"
    )
    composite_alert = next(
        alert for alert in result.alerts if alert.code == "RSI_SUPPORT_REBOUND_SETUP"
    )
    assert oversold_alert.policy is not None
    assert oversold_alert.policy.quality_gate == "degraded"
    assert composite_alert.policy is not None
    assert composite_alert.policy.lifecycle_state == "suppressed"
    assert composite_alert.policy.suppression_reason == "PATTERN_CONTEXT_MISSING"
    assert result.summary.quality_gate_counts["degraded"] == 2
    assert result.summary.lifecycle_counts["suppressed"] == 1


def test_alert_runtime_emits_active_composite_rebound_policy_when_support_confirms() -> (
    None
):
    service = AlertRuntimeService()
    indicator_series = TechnicalIndicatorSeriesArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalIndicatorSeriesFrameData(
                timeframe="1d",
                start="2026-03-01T00:00:00Z",
                end="2026-03-18T00:00:00Z",
                series={"RSI_14": {"2026-03-18T00:00:00Z": 28.0}},
                metadata=TechnicalIndicatorSeriesFrameMetadataData(
                    source_points=120,
                    max_points=120,
                    downsample_step=1,
                    sample_readiness="ready",
                    fidelity="high",
                    quality_flags=[],
                ),
            )
        },
    )
    pattern_pack = TechnicalPatternPackArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalPatternFrameData(
                support_levels=[{"price": 180.5}],
                resistance_levels=[],
                volume_profile_levels=[],
                breakouts=[],
                trendlines=[],
                pattern_flags=[],
                confluence_metadata={
                    "near_support": True,
                    "nearest_support": 180.5,
                    "confluence_state": "strong",
                },
                confidence_scores={},
            )
        },
    )

    result = service.compute(
        AlertRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-18T00:00:00Z",
            indicator_series=indicator_series,
            pattern_pack=pattern_pack,
        )
    )

    composite_alert = next(
        alert for alert in result.alerts if alert.code == "RSI_SUPPORT_REBOUND_SETUP"
    )
    assert composite_alert.policy is not None
    assert composite_alert.policy.policy_code == "TA_RSI_SUPPORT_REBOUND"
    assert composite_alert.policy.lifecycle_state == "active"
    assert composite_alert.policy.suppression_reason is None
    assert len(composite_alert.policy.evidence_refs) == 2
    assert "support proximity is confirmed" in (
        composite_alert.policy.trigger_reason or ""
    )
    assert result.summary.lifecycle_counts["active"] == 2


def test_alert_runtime_emits_monitoring_composite_rebound_policy_when_support_not_confirmed() -> (
    None
):
    service = AlertRuntimeService()
    indicator_series = TechnicalIndicatorSeriesArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalIndicatorSeriesFrameData(
                timeframe="1d",
                start="2026-03-01T00:00:00Z",
                end="2026-03-18T00:00:00Z",
                series={"RSI_14": {"2026-03-18T00:00:00Z": 29.5}},
                metadata=TechnicalIndicatorSeriesFrameMetadataData(
                    source_points=120,
                    max_points=120,
                    downsample_step=1,
                    sample_readiness="ready",
                    fidelity="high",
                    quality_flags=[],
                ),
            )
        },
    )
    pattern_pack = TechnicalPatternPackArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalPatternFrameData(
                support_levels=[{"price": 180.5}],
                resistance_levels=[],
                volume_profile_levels=[],
                breakouts=[],
                trendlines=[],
                pattern_flags=[],
                confluence_metadata={"near_support": False},
                confidence_scores={},
            )
        },
    )

    result = service.compute(
        AlertRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-18T00:00:00Z",
            indicator_series=indicator_series,
            pattern_pack=pattern_pack,
        )
    )

    composite_alert = next(
        alert for alert in result.alerts if alert.code == "RSI_SUPPORT_REBOUND_SETUP"
    )
    assert composite_alert.policy is not None
    assert composite_alert.policy.lifecycle_state == "monitoring"
    assert composite_alert.policy.suppression_reason == "NEAR_SUPPORT_NOT_CONFIRMED"
    assert result.summary.lifecycle_counts["monitoring"] == 1
