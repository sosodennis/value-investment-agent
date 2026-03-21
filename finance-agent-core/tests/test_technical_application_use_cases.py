from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from src.agents.technical.application.fracdiff_runtime_contracts import (
    FracdiffRuntimeResult,
)
from src.agents.technical.application.ports import (
    TechnicalInterpretationInput,
    TechnicalInterpretationResult,
)
from src.agents.technical.application.semantic_finalize_service import (
    assemble_semantic_finalize,
)
from src.agents.technical.application.semantic_interpretation_input_service import (
    build_interpretation_input,
    build_projection_context,
    load_projection_artifacts,
)
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    SemanticFinalizeResult,
    SemanticPipelineResult,
    TechnicalEvidenceBundle,
    TechnicalProjectionArtifacts,
)
from src.agents.technical.application.semantic_pipeline_service import (
    execute_semantic_pipeline,
)
from src.agents.technical.application.semantic_translate_context_service import (
    SemanticTranslateContext,
)
from src.agents.technical.application.state_updates import (
    build_data_fetch_error_update,
    build_data_fetch_success_update,
    build_fracdiff_error_update,
    build_fracdiff_success_update,
    build_semantic_error_update,
    build_semantic_success_update,
)
from src.agents.technical.application.use_cases.run_alerts_compute_use_case import (
    run_alerts_compute_use_case,
)
from src.agents.technical.application.use_cases.run_data_fetch_use_case import (
    run_data_fetch_use_case,
)
from src.agents.technical.application.use_cases.run_feature_compute_use_case import (
    run_feature_compute_use_case,
)
from src.agents.technical.application.use_cases.run_fracdiff_compute_use_case import (
    run_fracdiff_compute_use_case,
)
from src.agents.technical.application.use_cases.run_fusion_compute_use_case import (
    run_fusion_compute_use_case,
)
from src.agents.technical.application.use_cases.run_regime_compute_use_case import (
    run_regime_compute_use_case,
)
from src.agents.technical.application.use_cases.run_semantic_translate_use_case import (
    run_semantic_translate_use_case,
)
from src.agents.technical.domain.shared import FeatureFrame, FeaturePack, FeatureSummary
from src.agents.technical.interface.contracts import (
    AnalystPerspectiveModel,
    EvidenceBreakoutSignalModel,
    EvidenceScorecardSummaryModel,
    RegimeSummaryModel,
    StructureConfluenceSummaryModel,
)
from src.agents.technical.interface.serializers import build_full_report_payload
from src.agents.technical.subdomains.alerts import AlertRuntimeService
from src.agents.technical.subdomains.features import (
    FeatureRuntimeResult,
    FeatureRuntimeService,
    IndicatorSeriesFrameResult,
    IndicatorSeriesRuntimeResult,
)
from src.agents.technical.subdomains.features.application.indicator_series_runtime_service import (
    IndicatorSeriesFrameMetadata,
)
from src.agents.technical.subdomains.features.domain import (
    serialize_fracdiff_outputs,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataCacheMetadata,
    MarketDataOhlcvFetchResult,
    MarketDataProviderFailure,
)
from src.agents.technical.subdomains.regime.application.regime_runtime_service import (
    RegimeRuntimeResult,
)
from src.agents.technical.subdomains.regime.contracts import RegimeFrame, RegimePack
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeService,
    SemanticConfluenceResult,
    SemanticTagPolicyResult,
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalAlertPolicyMetadataData,
    TechnicalAlertsArtifactData,
    TechnicalAlertSignalData,
    TechnicalAlertSummaryData,
    TechnicalChartArtifactData,
    TechnicalFeatureFrameData,
    TechnicalFeatureIndicatorData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalIndicatorSeriesFrameData,
    TechnicalPatternFlagData,
    TechnicalPatternFrameData,
    TechnicalPatternLevelData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimeFrameData,
    TechnicalRegimePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
    TechnicalTimeseriesFrameData,
)
from src.shared.kernel.types import JSONObject


def test_safe_float_handles_nan_and_inf() -> None:
    assert safe_float(1.5) == 1.5
    assert safe_float("2.0") == 2.0
    assert safe_float(float("nan")) is None
    assert safe_float(float("inf")) is None
    assert safe_float("bad") is None


def test_serialize_fracdiff_outputs_converts_series_and_indicators() -> None:
    index = pd.to_datetime(["2025-01-01", "2025-01-02"])
    fd_series = pd.Series([1.25, math.nan], index=index)
    z_series = pd.Series([0.5, -1.2], index=index)

    result = serialize_fracdiff_outputs(
        fd_series=fd_series,
        z_score_series=z_series,
        bollinger_data={
            "upper": 1,
            "middle": 0.5,
            "lower": -1,
            "state": "INSIDE",
            "bandwidth": 0.2,
        },
        stat_strength_data={"value": 88.1},
        obv_data={
            "raw_obv_val": 10,
            "fd_obv_z": 0.8,
            "optimal_d": 0.42,
            "state": "BULLISH",
        },
    )

    assert result.fracdiff_series["2025-01-01"] == 1.25
    assert result.fracdiff_series["2025-01-02"] is None
    assert result.z_score_series["2025-01-02"] == -1.2
    assert result.bollinger.state == "INSIDE"
    assert result.stat_strength.value == 88.1
    assert result.obv.state == "BULLISH"


def test_build_full_report_payload_derives_states() -> None:
    payload = build_full_report_payload(
        ticker="GME",
        technical_context={
            "optimal_d": 0.62,
            "window_length": 252,
            "adf_statistic": -3.5,
            "adf_pvalue": 0.02,
            "z_score_latest": 2.1,
            "bollinger": {"state": "ABOVE"},
            "macd": {"momentum_state": "UP"},
            "obv": {"state": "BULLISH"},
            "statistical_strength_val": 79.3,
            "regime_summary": {"dominant_regime": "BULL_TREND", "timeframe_count": 1},
            "volume_profile_summary": {
                "timeframe": "1d",
                "level_count": 2,
                "dominant_level": {"price": 101.5},
            },
            "structure_confluence_summary": {
                "timeframe": "1d",
                "confluence_score": 0.7,
                "confluence_state": "strong",
            },
            "evidence_bundle": {
                "primary_timeframe": "1d",
                "support_levels": [98.5, 96.0],
                "resistance_levels": [104.0],
                "breakout_signals": [
                    {"name": "BREAKOUT_UP", "confidence": 0.7},
                ],
                "scorecard_summary": {
                    "timeframe": "1d",
                    "overall_score": 0.61,
                    "classic_label": "constructive",
                },
                "quant_context_summary": {
                    "timeframe": "1d",
                    "volatility_regime": "ELEVATED",
                    "liquidity_regime": "LIQUID",
                    "stretch_state": "HIGH",
                    "alignment_state": "FULL_BULLISH_ALIGNMENT",
                    "alignment_ratio": 1.0,
                },
                "regime_summary": {
                    "dominant_regime": "BULL_TREND",
                    "timeframe_count": 1,
                },
                "structure_confluence_summary": {
                    "timeframe": "1d",
                    "confluence_state": "strong",
                },
                "conflict_reasons": ["1d:quant_neutral"],
            },
            "signal_strength_summary": {
                "raw_value": 0.62,
                "effective_value": 0.43,
                "display_percent": 43.0,
                "strength_level": "weak",
                "calibration_status": "ineligible",
                "source": "fusion_runtime",
                "probability_eligible": False,
            },
            "setup_reliability_summary": {
                "level": "low",
                "calibration_status": "ineligible",
                "coverage_status": "partial",
                "conflict_level": "present",
                "reasons": [
                    "UNCALIBRATED",
                    "DEGRADED_INPUTS",
                    "CONFLICT_PRESENT",
                    "PARTIAL_COVERAGE",
                ],
                "recommended_reliance": "cautious",
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
            "regime_pack_id": "regime-1",
        },
        tags_dict={"direction": "bullish", "risk_level": "MEDIUM", "tags": ["A", "B"]},
        analyst_perspective={
            "stance": "BULLISH_WATCH",
            "stance_summary": "Bullish watch with medium risk.",
            "rationale_summary": "Signals point higher but confirmation is still needed.",
        },
        raw_data={"price_series": {"2025-01-01": 1.0}},
    )

    assert payload["direction"] == "BULLISH"
    assert payload["risk_level"] == "medium"
    assert payload["summary_tags"] == ["A", "B"]
    assert payload["regime_summary"]["dominant_regime"] == "BULL_TREND"
    assert payload["volume_profile_summary"]["dominant_level"]["price"] == 101.5
    assert payload["structure_confluence_summary"]["confluence_state"] == "strong"
    assert payload["evidence_bundle"]["primary_timeframe"] == "1d"
    assert payload["evidence_bundle"]["support_levels"] == [98.5, 96.0]
    assert payload["evidence_bundle"]["scorecard_summary"]["overall_score"] == 0.61
    assert (
        payload["evidence_bundle"]["quant_context_summary"]["alignment_state"]
        == "FULL_BULLISH_ALIGNMENT"
    )
    assert payload["signal_strength_summary"]["effective_value"] == 0.43
    assert payload["setup_reliability_summary"]["level"] == "low"
    assert payload["quality_summary"]["overall_quality"] == "medium"
    assert payload["quality_summary"]["degraded_reasons"] == ["1wk_QUANT_SKIPPED"]
    assert payload["alert_readout"]["highest_severity"] == "warning"
    assert (
        payload["alert_readout"]["top_alerts"][0]["policy_code"]
        == "TA_RSI_SUPPORT_REBOUND"
    )
    assert payload["observability_summary"]["primary_timeframe"] == "1d"
    assert payload["observability_summary"]["loaded_artifact_count"] == 5
    assert payload["observability_summary"]["missing_artifacts"] == [
        "direction_scorecard"
    ]
    assert payload["artifact_refs"]["regime_pack_id"] == "regime-1"
    assert derive_memory_strength(0.2) == "structurally_stable"
    assert derive_statistical_state(0.2) == "equilibrium"


@dataclass
class _SemanticProjectionPortStub:
    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]:
        _ = (price_artifact_id, chart_artifact_id)
        return None, None

    async def load_verification_report(self, artifact_id: str | None) -> object | None:
        _ = artifact_id
        return None

    async def load_pattern_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalPatternPackArtifactData | None:
        _ = artifact_id
        frame = TechnicalPatternFrameData(
            support_levels=[],
            resistance_levels=[],
            volume_profile_levels=[
                TechnicalPatternLevelData(
                    price=101.5,
                    strength=0.9,
                    touches=4,
                    label="HVN",
                )
            ],
            breakouts=[TechnicalPatternFlagData(name="BREAKOUT_UP", confidence=0.7)],
            trendlines=[TechnicalPatternFlagData(name="UPTREND", confidence=0.8)],
            pattern_flags=[],
            confluence_metadata={
                "confluence_score": 0.75,
                "confluence_state": "strong",
                "near_volume_node": True,
            },
            confidence_scores={},
        )
        return TechnicalPatternPackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={"1d": frame},
        )

    async def load_feature_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalFeaturePackArtifactData | None:
        _ = artifact_id
        return TechnicalFeaturePackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={
                "1d": TechnicalFeatureFrameData(
                    classic_indicators={
                        "ADX_14": TechnicalFeatureIndicatorData(
                            name="ADX_14",
                            value=19.65,
                            state="NEUTRAL",
                        ),
                        "ATRP_14": TechnicalFeatureIndicatorData(
                            name="ATRP_14",
                            value=0.023,
                            state="NEUTRAL",
                        ),
                        "ATR_14": TechnicalFeatureIndicatorData(
                            name="ATR_14",
                            value=5.763,
                            state="NEUTRAL",
                        ),
                    },
                    quant_features={
                        "FD_OPTIMAL_D": TechnicalFeatureIndicatorData(
                            name="FD_OPTIMAL_D",
                            value=0.6,
                            state="NEUTRAL",
                        ),
                        "FD_Z_SCORE": TechnicalFeatureIndicatorData(
                            name="FD_Z_SCORE",
                            value=-0.127,
                            state="NEUTRAL",
                        ),
                        "FD_ADF_STAT": TechnicalFeatureIndicatorData(
                            name="FD_ADF_STAT",
                            value=-5.559,
                            state="NEUTRAL",
                        ),
                    },
                )
            },
            feature_summary={
                "classic_count": 3,
                "quant_count": 3,
                "timeframe_count": 1,
                "ready_timeframes": ["1d"],
                "degraded_timeframes": ["1wk"],
                "regime_inputs_ready_timeframes": ["1d"],
                "unavailable_indicator_count": 1,
                "overall_quality": "medium",
            },
            degraded_reasons=["1wk_QUANT_SKIPPED"],
        )

    async def load_regime_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalRegimePackArtifactData | None:
        _ = artifact_id
        frame = TechnicalRegimeFrameData(
            timeframe="1d",
            regime="BULL_TREND",
            confidence=0.81,
            directional_bias="bullish",
            evidence=["adx=32.1", "atrp=0.018"],
        )
        return TechnicalRegimePackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={"1d": frame},
            regime_summary={"dominant_regime": "BULL_TREND", "timeframe_count": 1},
        )

    async def load_fusion_report(
        self,
        artifact_id: str | None,
    ) -> TechnicalFusionReportArtifactData | None:
        _ = artifact_id
        return TechnicalFusionReportArtifactData(
            schema_version="1.0",
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            direction="BULLISH_EXTENSION",
            risk_level="low",
            signal_strength_raw=0.74,
            signal_strength_effective=0.58,
            confidence_calibration={
                "mapping_source": "default_artifact",
                "mapping_version": "technical_direction_calibration_v1_2026_03_16",
                "calibration_applied": False,
            },
            confidence_eligibility={
                "eligible": False,
                "normalized_direction": "bullish",
                "reason_codes": ["DEGRADED_INPUTS_PRESENT", "CONFLICTS_PRESENT"],
            },
            conflict_reasons=["1d:quant_neutral"],
            regime_summary={"dominant_regime": "BULL_TREND", "timeframe_count": 1},
            degraded_reasons=["1wk_QUANT_SKIPPED"],
        )

    async def load_alerts(
        self,
        artifact_id: str | None,
    ) -> TechnicalAlertsArtifactData | None:
        _ = artifact_id
        return TechnicalAlertsArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            alerts=[
                TechnicalAlertSignalData(
                    code="RSI_OVERSOLD",
                    severity="warning",
                    timeframe="1d",
                    title="RSI oversold near support",
                    policy=TechnicalAlertPolicyMetadataData(
                        policy_code="TA_RSI_SUPPORT_REBOUND",
                        policy_version="1.0",
                        lifecycle_state="active",
                        quality_gate="passed",
                        trigger_reason="RSI oversold while price is near support",
                    ),
                ),
                TechnicalAlertSignalData(
                    code="FD_STRETCH",
                    severity="info",
                    timeframe="1d",
                    title="FD stretch worth monitoring",
                    policy=TechnicalAlertPolicyMetadataData(
                        policy_code="TA_FD_STRETCH_MONITOR",
                        policy_version="1.0",
                        lifecycle_state="monitoring",
                        quality_gate="degraded",
                        suppression_reason="Pattern confirmation still weak",
                    ),
                ),
            ],
            summary=TechnicalAlertSummaryData(
                total=2,
                policy_count=2,
                lifecycle_counts={"active": 1, "monitoring": 1},
                quality_gate_counts={"passed": 1, "degraded": 1},
            ),
            degraded_reasons=["ALERT_POLICY_DEGRADED"],
        )

    async def load_direction_scorecard(
        self,
        artifact_id: str | None,
    ) -> object | None:
        _ = artifact_id
        return None


@pytest.mark.asyncio
async def test_build_interpretation_input_projects_regime_and_structure_summaries() -> (
    None
):
    result = await build_interpretation_input(
        ticker="AAPL",
        technical_context={
            "feature_pack_id": "feature-1",
            "pattern_pack_id": "pattern-1",
            "regime_pack_id": "regime-1",
            "fusion_report_id": "fusion-1",
            "alerts_id": "alerts-1",
        },
        tags_result=SemanticTagPolicyResult(
            tags=["TREND_ACTIVE"],
            direction="BULLISH_EXTENSION",
            risk_level="low",
            memory_strength="balanced",
            statistical_state="deviating",
            z_score=1.4,
            confluence=SemanticConfluenceResult(
                bollinger_state="INSIDE",
                statistical_strength=72.0,
                macd_momentum="BULLISH",
                obv_state="BULLISH",
            ),
            evidence_list=["bullish_breakout"],
        ),
        backtest_context_result=BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
        ),
        technical_port=_SemanticProjectionPortStub(),
    )

    assert result.setup_context is not None
    assert result.setup_context["regime_summary"]["dominant_regime"] == "BULL_TREND"
    assert (
        result.setup_context["volume_profile_summary"]["dominant_level"]["label"]
        == "HVN"
    )
    assert (
        result.setup_context["structure_confluence_summary"]["confluence_state"]
        == "strong"
    )
    assert len(result.signal_explainer_context) == 3
    assert result.signal_explainer_context[0].signal == "FD_OPTIMAL_D"
    assert result.signal_explainer_context[1].signal == "ADX_14"
    assert result.signal_explainer_context[2].signal == "FD_Z_SCORE"
    assert (
        result.signal_explainer_context[0].current_reading_hint
        == "The current reading suggests the market still carries noticeable trend memory or persistence."
    )
    assert result.diagnostics_context is not None
    assert result.diagnostics_context["degraded_reasons"] == ["1wk_QUANT_SKIPPED"]


@pytest.mark.asyncio
async def test_load_projection_artifacts_builds_reusable_evidence_bundle() -> None:
    artifacts = await load_projection_artifacts(
        technical_context={
            "feature_pack_id": "feature-1",
            "pattern_pack_id": "pattern-1",
            "regime_pack_id": "regime-1",
            "fusion_report_id": "fusion-1",
            "alerts_id": "alerts-1",
        },
        technical_port=_SemanticProjectionPortStub(),
    )

    assert artifacts.evidence_bundle is not None
    assert artifacts.evidence_bundle.primary_timeframe == "1d"
    assert artifacts.evidence_bundle.support_levels == ()
    assert artifacts.evidence_bundle.regime_summary is not None
    assert artifacts.evidence_bundle.regime_summary.dominant_regime == "BULL_TREND"
    projection_context = build_projection_context(artifacts=artifacts)
    assert projection_context["regime_summary"]["dominant_regime"] == "BULL_TREND"
    assert (
        projection_context["structure_confluence_summary"]["confluence_state"]
        == "strong"
    )
    assert projection_context["signal_strength_summary"]["effective_value"] == 0.58
    assert projection_context["signal_strength_summary"]["strength_level"] == "moderate"
    assert projection_context["setup_reliability_summary"]["level"] == "low"
    assert (
        projection_context["setup_reliability_summary"]["recommended_reliance"]
        == "cautious"
    )
    assert projection_context["quality_summary"]["is_degraded"] is True
    assert projection_context["quality_summary"]["overall_quality"] == "medium"
    assert projection_context["alert_readout"]["total_alerts"] == 2
    assert (
        projection_context["alert_readout"]["top_alerts"][0]["policy_code"]
        == "TA_RSI_SUPPORT_REBOUND"
    )
    assert projection_context["observability_summary"]["loaded_artifact_count"] == 5
    assert projection_context["observability_summary"]["missing_artifacts"] == [
        "direction_scorecard"
    ]
    assert projection_context["observability_summary"]["degraded_reason_count"] == 2


def test_assemble_semantic_finalize_builds_update_and_raw_data() -> None:
    price_data = PriceSeriesArtifactData(
        price_series={"2025-01-01": 10.0},
        volume_series={"2025-01-01": 1000.0},
    )
    chart_data = TechnicalChartArtifactData(
        fracdiff_series={"2025-01-01": 0.1},
        z_score_series={"2025-01-01": 1.7},
        indicators={"bollinger": {"state": "INSIDE"}, "obv": {"state": "NEUTRAL"}},
    )

    result = assemble_semantic_finalize(
        ticker="GME",
        technical_context={
            "optimal_d": 0.44,
            "window_length": 252,
            "adf_statistic": -3.2,
            "adf_pvalue": 0.03,
            "z_score_latest": 1.7,
            "bollinger": {"state": "INSIDE"},
            "macd": {"momentum_state": "UP"},
            "obv": {"state": "NEUTRAL"},
            "statistical_strength_val": 66.0,
        },
        tags_result=SemanticTagPolicyResult(
            direction="bullish",
            risk_level="MEDIUM",
            tags=["MeanReversion"],
            statistical_state="deviating",
            memory_strength="balanced",
            z_score=1.7,
            confluence=SemanticConfluenceResult(
                bollinger_state="INSIDE",
                statistical_strength=66.0,
                macd_momentum="UP",
                obv_state="NEUTRAL",
            ),
            evidence_list=[],
        ),
        analyst_perspective=AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with medium risk.",
            rationale_summary="Signals point higher but confirmation is still needed.",
        ),
        price_data=price_data,
        chart_data=chart_data,
        build_full_report_payload_fn=build_full_report_payload,
    )

    assert result.direction == "BULLISH"
    assert result.ta_update["signal"] == "bullish"
    assert result.ta_update["memory_strength"] == "balanced"
    assert result.raw_data["price_series"]["2025-01-01"] == 10.0
    assert result.full_report_data_raw["direction"] == "BULLISH"
    assert result.full_report_data_raw["evidence_bundle"] is None


def test_semantic_command_update_builders() -> None:
    success = build_semantic_success_update(
        {"signal": "bullish"},
        is_degraded=False,
        degraded_reasons=[],
    )
    error = build_semantic_error_update("boom")

    assert success.update["current_node"] == "semantic_translate"
    assert success.update["node_statuses"]["technical_analysis"] == "done"
    assert success.update["technical_analysis"]["is_degraded"] is False
    assert success.update["technical_analysis"]["degraded_reasons"] == []
    assert error.update["node_statuses"]["technical_analysis"] == "error"
    assert error.update["error_logs"][0]["error"] == "boom"


def test_data_fetch_update_builders() -> None:
    success = build_data_fetch_success_update(
        price_artifact_id="price-1",
        timeseries_bundle_id="bundle-1",
        is_degraded=True,
        degraded_reasons=["1h_UNAVAILABLE"],
        artifact={
            "kind": "technical_analysis.output",
            "version": "v1",
            "summary": "ok",
            "preview": None,
            "reference": None,
        },
    )
    error = build_data_fetch_error_update("no ticker")
    assert success["technical_analysis"]["price_artifact_id"] == "price-1"
    assert success["technical_analysis"]["is_degraded"] is True
    assert success["technical_analysis"]["degraded_reasons"] == ["1h_UNAVAILABLE"]
    assert success["node_statuses"]["technical_analysis"] == "running"
    assert error["node_statuses"]["technical_analysis"] == "error"
    assert error["error_logs"][0]["node"] == "data_fetch"


def test_fracdiff_update_builders() -> None:
    success = build_fracdiff_success_update(
        latest_price=12.3,
        optimal_d=0.42,
        z_score_latest=1.1,
        chart_data_id="chart-1",
        window_length=252,
        adf_statistic=-3.2,
        adf_pvalue=0.02,
        bollinger={"state": "INSIDE"},
        statistical_strength_val=77.0,
        macd={"momentum_state": "UP"},
        obv={"state": "BULLISH"},
        artifact={
            "kind": "technical_analysis.output",
            "version": "v1",
            "summary": "ok",
            "preview": None,
            "reference": None,
        },
    )
    error = build_fracdiff_error_update("bad")
    assert success["technical_analysis"]["chart_data_id"] == "chart-1"
    assert success["current_node"] == "fracdiff_compute"
    assert error["error_logs"][0]["node"] == "fracdiff_compute"


@dataclass
class _FakeDataFetchRuntime:
    saved_data: JSONObject | None = None
    saved_bundle: JSONObject | None = None

    async def save_price_series(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_data = data
        return "price-artifact-id"

    async def save_timeseries_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_bundle = data
        return "bundle-artifact-id"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        _ = (summary, preview)
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


class _ProviderFailureOnly:
    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        _ = (ticker_symbol, period, interval)
        return MarketDataOhlcvFetchResult(
            data=None,
            failure=MarketDataProviderFailure(
                failure_code="TECHNICAL_OHLCV_FETCH_FAILED",
                reason="upstream timeout",
            ),
        )


class _ProviderPartialCoverage:
    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        _ = (ticker_symbol, period)
        if interval == "1h":
            return MarketDataOhlcvFetchResult(
                data=None,
                failure=MarketDataProviderFailure(
                    failure_code="TECHNICAL_OHLCV_EMPTY",
                    reason="intraday unavailable",
                ),
            )
        index = pd.to_datetime(["2026-02-10", "2026-02-11", "2026-02-12"], utc=True)
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "price": [100.5, 101.5, 102.5],
                "volume": [1000.0, 1100.0, 1200.0],
            },
            index=index,
        )
        return MarketDataOhlcvFetchResult(
            data=frame,
            cache=MarketDataCacheMetadata(
                cache_hit=False,
                cache_age_seconds=12.0,
                cache_bucket=f"{interval}-bucket",
            ),
        )


@dataclass
class _FracdiffUseCaseRuntime:
    captured_key_prefix: str | None = None

    async def load_price_series(
        self, artifact_id: str
    ) -> PriceSeriesArtifactData | None:
        _ = artifact_id
        return PriceSeriesArtifactData(
            price_series={"2025-01-01": 10.0, "2025-01-02": 10.5},
            volume_series={"2025-01-01": 1000.0, "2025-01-02": 1100.0},
        )

    async def save_chart_data(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (data, produced_by)
        self.captured_key_prefix = key_prefix
        return "chart-1"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


class _FracdiffRuntime:
    def compute(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
    ) -> FracdiffRuntimeResult:
        _ = (prices, volumes)
        return FracdiffRuntimeResult(
            latest_price=10.5,
            optimal_d=0.45,
            z_score_latest=1.1,
            window_length=120,
            adf_statistic=-3.0,
            adf_pvalue=0.02,
            bollinger={"state": "INSIDE"},
            statistical_strength_val=75.0,
            macd={"momentum_state": "UP"},
            obv={"state": "BULLISH"},
            chart_data={"z_score_series": {"2025-01-01": 1.1}},
        )


@dataclass
class _FeatureRuntimeStub:
    def compute(self, request: object) -> FeatureRuntimeResult:
        feature_pack = FeaturePack(
            ticker=getattr(request, "ticker", "AAPL"),
            as_of=getattr(request, "as_of", "2026-02-12T00:00:00Z"),
            timeframes={"1d": FeatureFrame()},
            feature_summary=FeatureSummary(
                classic_count=0,
                quant_count=0,
                timeframe_count=1,
                ready_timeframes=("1d",),
                degraded_timeframes=(),
                regime_inputs_ready_timeframes=(),
                unavailable_indicator_count=0,
                overall_quality="high",
            ),
        )
        return FeatureRuntimeResult(feature_pack=feature_pack, degraded_reasons=[])


@dataclass
class _IndicatorSeriesRuntimeStub:
    def compute(self, request: object) -> IndicatorSeriesRuntimeResult:
        frame = IndicatorSeriesFrameResult(
            timeframe="1d",
            start="2026-02-01T00:00:00Z",
            end="2026-02-12T00:00:00Z",
            series={"RSI_14": {"2026-02-10": 45.0}},
            timezone="UTC",
            metadata=IndicatorSeriesFrameMetadata(
                source_points=1,
                max_points=1500,
                downsample_step=1,
                source_timeframe="1d",
                source_price_basis="close",
                effective_sample_count=1,
                minimum_sample_count=300,
                sample_readiness="partial",
                fidelity="high",
                quality_flags=("QUANT_SKIPPED",),
            ),
        )
        return IndicatorSeriesRuntimeResult(
            ticker=getattr(request, "ticker", "AAPL"),
            as_of=getattr(request, "as_of", "2026-02-12T00:00:00Z"),
            timeframes={"1d": frame},
            degraded_reasons=[],
        )


@dataclass
class _FeatureRuntimeDegradedStub:
    def compute(self, request: object) -> FeatureRuntimeResult:
        feature_pack = _FeatureRuntimeStub().compute(request).feature_pack
        return FeatureRuntimeResult(
            feature_pack=feature_pack,
            degraded_reasons=["1wk_QUANT_SKIPPED"],
        )


@dataclass
class _IndicatorSeriesRuntimeDegradedStub:
    def compute(self, request: object) -> IndicatorSeriesRuntimeResult:
        result = _IndicatorSeriesRuntimeStub().compute(request)
        return IndicatorSeriesRuntimeResult(
            ticker=result.ticker,
            as_of=result.as_of,
            timeframes=result.timeframes,
            degraded_reasons=["1wk_QUANT_SKIPPED"],
        )


@dataclass
class _FeatureComputeRuntimeStub:
    saved_feature_pack: JSONObject | None = None
    saved_indicator_series: JSONObject | None = None

    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        frame = TechnicalTimeseriesFrameData(
            timeframe="1d",
            start="2026-02-01T00:00:00Z",
            end="2026-02-12T00:00:00Z",
            open_series={"2026-02-10": 100.0},
            high_series={"2026-02-10": 101.0},
            low_series={"2026-02-10": 99.0},
            close_series={"2026-02-10": 100.5},
            price_series={"2026-02-10": 100.5},
            volume_series={"2026-02-10": 1500.0},
            timezone="UTC",
            metadata=None,
        )
        return TechnicalTimeseriesBundleArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            frames={"1d": frame},
        )

    async def save_feature_pack(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_feature_pack = data
        return "feature-1"

    async def save_indicator_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_indicator_series = data
        return "series-1"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        _ = (summary, preview)
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


@dataclass
class _AlertsComputeRuntimeStub:
    saved_alerts: JSONObject | None = None

    async def load_indicator_series(
        self, artifact_id: str
    ) -> TechnicalIndicatorSeriesArtifactData | None:
        _ = artifact_id
        return None

    async def load_pattern_pack(
        self, artifact_id: str
    ) -> TechnicalPatternPackArtifactData | None:
        _ = artifact_id
        return None

    async def save_alerts(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_alerts = data
        return "alerts-1"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        _ = (summary, preview)
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


async def _load_alert_indicator_series_ready(
    artifact_id: str,
) -> TechnicalIndicatorSeriesArtifactData | None:
    _ = artifact_id
    return TechnicalIndicatorSeriesArtifactData(
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
                metadata={
                    "source_points": 120,
                    "max_points": 120,
                    "downsample_step": 1,
                    "source_timeframe": "1d",
                    "source_price_basis": "close",
                    "effective_sample_count": 120,
                    "minimum_sample_count": 30,
                    "sample_readiness": "ready",
                    "fidelity": "high",
                    "quality_flags": [],
                },
            )
        },
    )


async def _load_alert_pattern_pack_ready(
    artifact_id: str,
) -> TechnicalPatternPackArtifactData | None:
    _ = artifact_id
    return TechnicalPatternPackArtifactData(
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


async def _load_alert_indicator_series_oversold(
    artifact_id: str,
) -> TechnicalIndicatorSeriesArtifactData | None:
    _ = artifact_id
    return TechnicalIndicatorSeriesArtifactData(
        ticker="AAPL",
        as_of="2026-03-18T00:00:00Z",
        timeframes={
            "1d": TechnicalIndicatorSeriesFrameData(
                timeframe="1d",
                start="2026-03-01T00:00:00Z",
                end="2026-03-18T00:00:00Z",
                series={"RSI_14": {"2026-03-18T00:00:00Z": 28.0}},
                metadata={
                    "source_points": 120,
                    "max_points": 120,
                    "downsample_step": 1,
                    "source_timeframe": "1d",
                    "source_price_basis": "close",
                    "effective_sample_count": 120,
                    "minimum_sample_count": 30,
                    "sample_readiness": "ready",
                    "fidelity": "high",
                    "quality_flags": [],
                },
            )
        },
    )


async def _load_alert_pattern_pack_support_confirmed(
    artifact_id: str,
) -> TechnicalPatternPackArtifactData | None:
    _ = artifact_id
    return TechnicalPatternPackArtifactData(
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


@dataclass
class _FusionComputeRuntimeStub:
    saved_fusion_report: JSONObject | None = None
    saved_scorecard: JSONObject | None = None

    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        frame = TechnicalTimeseriesFrameData(
            timeframe="1d",
            start="2026-02-01T00:00:00Z",
            end="2026-02-12T00:00:00Z",
            open_series={"2026-02-10": 100.0},
            high_series={"2026-02-10": 101.0},
            low_series={"2026-02-10": 99.0},
            close_series={"2026-02-10": 100.5},
            price_series={"2026-02-10": 100.5},
            volume_series={"2026-02-10": 1500.0},
            timezone="UTC",
            metadata=None,
        )
        return TechnicalTimeseriesBundleArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            frames={"1d": frame},
            degraded_reasons=["1h_UNAVAILABLE"],
        )

    async def load_feature_pack(
        self, artifact_id: str
    ) -> TechnicalFeaturePackArtifactData | None:
        _ = artifact_id
        indicator = TechnicalFeatureIndicatorData(
            name="RSI",
            value=45.0,
            state="neutral",
        )
        frame = TechnicalFeatureFrameData(
            classic_indicators={"rsi": indicator},
            quant_features={},
        )
        return TechnicalFeaturePackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={"1d": frame},
            degraded_reasons=["1wk_QUANT_SKIPPED"],
        )

    async def load_pattern_pack(
        self, artifact_id: str
    ) -> TechnicalPatternPackArtifactData | None:
        _ = artifact_id
        frame = TechnicalPatternFrameData(
            support_levels=[],
            resistance_levels=[],
            breakouts=[
                TechnicalPatternFlagData(name="breakout_up", confidence=0.7),
            ],
            trendlines=[],
            pattern_flags=[],
            confidence_scores={},
        )
        return TechnicalPatternPackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={"1d": frame},
        )

    async def load_regime_pack(
        self, artifact_id: str
    ) -> TechnicalRegimePackArtifactData | None:
        _ = artifact_id
        frame = TechnicalRegimeFrameData(
            timeframe="1d",
            regime="BULL_TREND",
            confidence=0.74,
            directional_bias="bullish",
            evidence=["bias=bullish", "adx=31.2"],
            metadata={"bias_score": 3},
        )
        return TechnicalRegimePackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={"1d": frame},
            regime_summary={"dominant_regime": "BULL_TREND", "timeframe_count": 1},
        )

    async def save_fusion_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_fusion_report = data
        return "fusion-1"

    async def save_direction_scorecard(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_scorecard = data
        return "scorecard-1"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        _ = (summary, preview)
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


@dataclass
class _RegimeRuntimeStub:
    def compute(self, request: object) -> RegimeRuntimeResult:
        ticker = getattr(request, "ticker", "AAPL")
        as_of = getattr(request, "as_of", "2026-02-12T00:00:00Z")
        return RegimeRuntimeResult(
            regime_pack=RegimePack(
                ticker=ticker,
                as_of=as_of,
                timeframes={
                    "1d": RegimeFrame(
                        timeframe="1d",
                        regime="HIGH_VOL_CHOP",
                        confidence=0.68,
                        directional_bias="neutral",
                        evidence=("atrp=0.0400",),
                        metadata={"bias_score": 0},
                    )
                },
                regime_summary={
                    "dominant_regime": "HIGH_VOL_CHOP",
                    "timeframe_count": 1,
                },
            ),
            degraded_reasons=[],
        )


@dataclass
class _RegimeComputeRuntimeStub:
    saved_regime_pack: JSONObject | None = None
    feature_pack: TechnicalFeaturePackArtifactData | None = None
    indicator_series: TechnicalIndicatorSeriesArtifactData | None = None

    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        frame = TechnicalTimeseriesFrameData(
            timeframe="1d",
            start="2026-02-01T00:00:00Z",
            end="2026-02-12T00:00:00Z",
            open_series={"2026-02-10": 100.0},
            high_series={"2026-02-10": 101.0},
            low_series={"2026-02-10": 99.0},
            close_series={"2026-02-10": 100.5},
            price_series={"2026-02-10": 100.5},
            volume_series={"2026-02-10": 1500.0},
            timezone="UTC",
            metadata=None,
        )
        return TechnicalTimeseriesBundleArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            frames={"1d": frame},
        )

    async def load_feature_pack(
        self, artifact_id: str | None
    ) -> TechnicalFeaturePackArtifactData | None:
        _ = artifact_id
        return self.feature_pack

    async def load_indicator_series(
        self, artifact_id: str | None
    ) -> TechnicalIndicatorSeriesArtifactData | None:
        _ = artifact_id
        return self.indicator_series

    async def save_regime_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (produced_by, key_prefix)
        self.saved_regime_pack = data
        return "regime-1"

    def build_progress_artifact(
        self, summary: str, preview: JSONObject
    ) -> dict[str, object]:
        _ = (summary, preview)
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
        }


@dataclass
class _RegimeRuntimeSpy:
    captured_metadata: dict[str, object] | None = None

    def compute(self, request: object) -> RegimeRuntimeResult:
        series_by_timeframe = getattr(request, "series_by_timeframe", {})
        series = series_by_timeframe.get("1d")
        self.captured_metadata = getattr(series, "metadata", None)
        return _RegimeRuntimeStub().compute(request)


@pytest.mark.asyncio
async def test_run_data_fetch_handles_typed_provider_failure() -> None:
    runtime = _FakeDataFetchRuntime()
    state: dict[str, object] = {"intent_extraction": {"resolved_ticker": "AAPL"}}
    result = await run_data_fetch_use_case(
        runtime,
        state,
        market_data_provider=_ProviderFailureOnly(),
    )

    assert result.goto == "END"
    assert result.update["node_statuses"]["technical_analysis"] == "error"
    assert "Empty daily data returned" in result.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_run_data_fetch_marks_partial_bundle_as_degraded() -> None:
    runtime = _FakeDataFetchRuntime()
    state: dict[str, object] = {"intent_extraction": {"resolved_ticker": "AAPL"}}

    with patch(
        "src.agents.technical.application.use_cases.run_data_fetch_use_case.log_event"
    ) as mock_log:
        result = await run_data_fetch_use_case(
            runtime,
            state,
            market_data_provider=_ProviderPartialCoverage(),
        )

    assert result.goto == "feature_compute"
    technical_state = result.update["technical_analysis"]
    assert technical_state["is_degraded"] is True
    assert technical_state["degraded_reasons"] == ["1h_UNAVAILABLE"]
    assert runtime.saved_bundle is not None
    assert runtime.saved_bundle["degraded_reasons"] == ["1h_UNAVAILABLE"]
    daily_metadata = runtime.saved_bundle["frames"]["1d"]["metadata"]
    assert daily_metadata["row_count"] == 3
    assert daily_metadata["price_basis"] == "close"
    assert daily_metadata["timezone_normalized"] is True
    assert daily_metadata["cache_bucket"] == "1d-bucket"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "technical_data_fetch_completed"
    )
    assert completion_call.kwargs["fields"]["is_degraded"] is True


@pytest.mark.asyncio
async def test_run_fracdiff_compute_uses_resolved_ticker_for_artifact_key_prefix() -> (
    None
):
    runtime = _FracdiffUseCaseRuntime()
    state: dict[str, object] = {
        "ticker": "ROOT_TICKER_SHOULD_NOT_BE_USED",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"price_artifact_id": "price-1"},
    }

    result = await run_fracdiff_compute_use_case(
        runtime,
        state,
        fracdiff_runtime=_FracdiffRuntime(),
    )

    assert result.goto == "semantic_translate"
    assert runtime.captured_key_prefix == "AAPL"


@pytest.mark.asyncio
async def test_run_feature_compute_writes_indicator_series_id() -> None:
    runtime = _FeatureComputeRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_feature_compute_use_case(
        runtime,
        state,
        feature_runtime=_FeatureRuntimeStub(),
        indicator_series_runtime=_IndicatorSeriesRuntimeStub(),
    )

    assert result.goto == "pattern_compute"
    assert runtime.saved_indicator_series is not None
    assert runtime.saved_feature_pack is not None
    technical_state = result.update["technical_analysis"]
    assert technical_state["indicator_series_id"] == "series-1"
    indicator_metadata = runtime.saved_indicator_series["timeframes"]["1d"]["metadata"]
    assert indicator_metadata["source_timeframe"] == "1d"
    assert indicator_metadata["sample_readiness"] == "partial"
    assert indicator_metadata["quality_flags"] == ["QUANT_SKIPPED"]
    feature_summary = runtime.saved_feature_pack["feature_summary"]
    assert feature_summary["overall_quality"] == "high"
    assert feature_summary["ready_timeframes"] == ["1d"]


@pytest.mark.asyncio
async def test_run_feature_compute_dedupes_degraded_reasons() -> None:
    runtime = _FeatureComputeRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    with patch(
        "src.agents.technical.application.use_cases.run_feature_compute_use_case.log_event"
    ) as mock_log:
        result = await run_feature_compute_use_case(
            runtime,
            state,
            feature_runtime=_FeatureRuntimeDegradedStub(),
            indicator_series_runtime=_IndicatorSeriesRuntimeDegradedStub(),
        )

    assert result.goto == "pattern_compute"
    technical_state = result.update["technical_analysis"]
    assert technical_state["is_degraded"] is True
    assert technical_state["degraded_reasons"] == ["1wk_QUANT_SKIPPED"]
    degraded_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "technical_feature_compute_degraded"
    )
    assert degraded_call.kwargs["fields"]["degraded_reasons"] == ["1wk_QUANT_SKIPPED"]


@dataclass
class _FeatureComputeLongSeriesRuntimeStub(_FeatureComputeRuntimeStub):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        return TechnicalTimeseriesBundleArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            frames={
                "1d": _build_timeseries_frame_data(
                    timeframe="1d",
                    start=datetime(2025, 1, 1, tzinfo=UTC),
                    periods=320,
                    base=100.0,
                    drift=0.35,
                    volume_base=1_000_000,
                    volume_step=4_500,
                )
            },
        )


@dataclass
class _FeatureComputeMultiTimeframeLongSeriesRuntimeStub(_FeatureComputeRuntimeStub):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        return TechnicalTimeseriesBundleArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            frames={
                "1d": _build_timeseries_frame_data(
                    timeframe="1d",
                    start=datetime(2025, 1, 1, tzinfo=UTC),
                    periods=320,
                    base=100.0,
                    drift=0.35,
                    volume_base=1_000_000,
                    volume_step=4_500,
                ),
                "1wk": _build_timeseries_frame_data(
                    timeframe="1wk",
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    periods=90,
                    base=90.0,
                    drift=0.8,
                    volume_base=1_500_000,
                    volume_step=6_000,
                ),
                "1h": _build_timeseries_frame_data(
                    timeframe="1h",
                    start=datetime(2026, 1, 1, tzinfo=UTC),
                    periods=120,
                    base=101.0,
                    drift=0.08,
                    volume_base=300_000,
                    volume_step=2_000,
                ),
            },
        )


def _build_timeseries_frame_data(
    *,
    timeframe: str,
    start: datetime,
    periods: int,
    base: float,
    drift: float,
    volume_base: int,
    volume_step: int,
) -> TechnicalTimeseriesFrameData:
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    previous_close = base
    for idx in range(periods):
        timestamp = (start + timedelta(days=idx)).isoformat()
        close = base + (idx * drift) + ((idx % 5) - 2) * 0.24
        open_price = previous_close + ((idx % 3) - 1) * 0.18
        high = max(open_price, close) + 1.1
        low = min(open_price, close) - 0.9
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(volume_base + idx * volume_step)
        previous_close = close
    return TechnicalTimeseriesFrameData(
        timeframe=timeframe,
        start=min(price_series),
        end=max(price_series),
        open_series=open_series,
        high_series=high_series,
        low_series=low_series,
        close_series=close_series,
        price_series=price_series,
        volume_series=volume_series,
        timezone="UTC",
        metadata=None,
    )


@pytest.mark.asyncio
async def test_run_feature_compute_serializes_volatility_regime_quant_features() -> (
    None
):
    runtime = _FeatureComputeLongSeriesRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_feature_compute_use_case(
        runtime,
        state,
        feature_runtime=FeatureRuntimeService(),
        indicator_series_runtime=_IndicatorSeriesRuntimeStub(),
    )

    assert result.goto == "pattern_compute"
    assert runtime.saved_feature_pack is not None
    quant_features = runtime.saved_feature_pack["timeframes"]["1d"]["quant_features"]
    assert quant_features["VOL_REALIZED_20"]["value"] is not None
    assert quant_features["VOL_DOWNSIDE_20"]["value"] is not None
    assert quant_features["VOL_PERCENTILE_252"]["state"] in {
        "COMPRESSED",
        "NORMAL",
        "ELEVATED",
    }
    assert quant_features["VOL_REALIZED_20"]["provenance"]["method"] == (
        "realized_volatility_20"
    )
    assert quant_features["VOL_PERCENTILE_252"]["quality"]["warmup_status"] == "READY"


@pytest.mark.asyncio
async def test_run_feature_compute_serializes_liquidity_proxy_quant_features() -> None:
    runtime = _FeatureComputeLongSeriesRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_feature_compute_use_case(
        runtime,
        state,
        feature_runtime=FeatureRuntimeService(),
        indicator_series_runtime=_IndicatorSeriesRuntimeStub(),
    )

    assert result.goto == "pattern_compute"
    assert runtime.saved_feature_pack is not None
    quant_features = runtime.saved_feature_pack["timeframes"]["1d"]["quant_features"]
    assert quant_features["DOLLAR_VOLUME_20"]["value"] is not None
    assert quant_features["AMIHUD_ILLIQUIDITY_20"]["value"] is not None
    assert quant_features["DOLLAR_VOLUME_PERCENTILE_252"]["state"] in {
        "THIN",
        "NORMAL",
        "LIQUID",
    }
    assert quant_features["DOLLAR_VOLUME_20"]["provenance"]["method"] == (
        "average_dollar_volume_20"
    )
    assert (
        quant_features["DOLLAR_VOLUME_PERCENTILE_252"]["quality"]["warmup_status"]
        == "READY"
    )


@pytest.mark.asyncio
async def test_run_feature_compute_serializes_normalized_distance_quant_features() -> (
    None
):
    runtime = _FeatureComputeLongSeriesRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_feature_compute_use_case(
        runtime,
        state,
        feature_runtime=FeatureRuntimeService(),
        indicator_series_runtime=_IndicatorSeriesRuntimeStub(),
    )

    assert result.goto == "pattern_compute"
    assert runtime.saved_feature_pack is not None
    quant_features = runtime.saved_feature_pack["timeframes"]["1d"]["quant_features"]
    assert quant_features["PRICE_VS_SMA20_Z"]["value"] is not None
    assert quant_features["RETURN_ZSCORE_20"]["value"] is not None
    assert quant_features["PRICE_DISTANCE_ATR_14"]["value"] is not None
    assert quant_features["PRICE_VS_SMA20_Z"]["provenance"]["method"] == (
        "price_vs_sma20_zscore"
    )
    assert quant_features["RETURN_ZSCORE_20"]["quality"]["warmup_status"] == "READY"


@pytest.mark.asyncio
async def test_run_feature_compute_serializes_cross_timeframe_alignment_quant_features() -> (
    None
):
    runtime = _FeatureComputeMultiTimeframeLongSeriesRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_feature_compute_use_case(
        runtime,
        state,
        feature_runtime=FeatureRuntimeService(),
        indicator_series_runtime=_IndicatorSeriesRuntimeStub(),
    )

    assert result.goto == "pattern_compute"
    assert runtime.saved_feature_pack is not None
    quant_features = runtime.saved_feature_pack["timeframes"]["1d"]["quant_features"]
    assert quant_features["MTF_ALIGNMENT_RATIO"]["value"] is not None
    assert quant_features["HTF_CONFIRMATION"]["value"] is not None
    assert quant_features["LTF_CONFIRMATION"]["value"] is not None
    assert quant_features["MTF_ALIGNMENT_RATIO"]["provenance"]["method"] == (
        "mtf_alignment_ratio"
    )
    assert (
        quant_features["HTF_CONFIRMATION"]["metadata"]["comparison_timeframe"] == "1wk"
    )
    assert (
        quant_features["LTF_CONFIRMATION"]["metadata"]["comparison_timeframe"] == "1h"
    )


def test_feature_pack_payload_serializes_indicator_provenance_and_quality() -> None:
    indicator = TechnicalFeatureIndicatorData(
        name="ADX_14",
        value=21.5,
        state="NEUTRAL",
        provenance={
            "method": "adx_14",
            "input_basis": "high_low_close",
            "source_timeframe": "1d",
            "calculation_version": "technical_feature_contract_v1",
        },
        quality={
            "effective_sample_count": 120,
            "minimum_samples": 14,
            "warmup_status": "READY",
            "fidelity": "high",
            "quality_flags": [],
        },
        metadata={"effective_sample_count": 120},
    )
    payload = TechnicalFeaturePackArtifactData(
        ticker="AAPL",
        as_of="2026-02-12T00:00:00Z",
        timeframes={
            "1d": TechnicalFeatureFrameData(
                classic_indicators={"ADX_14": indicator},
                quant_features={},
            )
        },
        feature_summary={
            "classic_count": 1,
            "quant_count": 0,
            "timeframe_count": 1,
            "ready_timeframes": ["1d"],
            "degraded_timeframes": [],
            "regime_inputs_ready_timeframes": [],
            "unavailable_indicator_count": 0,
            "overall_quality": "high",
        },
    ).model_dump(mode="json")

    parsed_indicator = payload["timeframes"]["1d"]["classic_indicators"]["ADX_14"]
    assert parsed_indicator["provenance"]["source_timeframe"] == "1d"
    assert parsed_indicator["quality"]["warmup_status"] == "READY"
    assert payload["feature_summary"]["overall_quality"] == "high"


@pytest.mark.asyncio
async def test_run_alerts_compute_writes_alerts_id() -> None:
    runtime = _AlertsComputeRuntimeStub()
    runtime.load_indicator_series = _load_alert_indicator_series_ready  # type: ignore[method-assign]
    runtime.load_pattern_pack = _load_alert_pattern_pack_ready  # type: ignore[method-assign]
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {
            "indicator_series_id": "series-1",
            "pattern_pack_id": "pattern-1",
        },
    }

    result = await run_alerts_compute_use_case(
        runtime,
        state,
        alert_runtime=AlertRuntimeService(),
    )

    assert result.goto == "regime_compute"
    assert runtime.saved_alerts is not None
    assert (
        runtime.saved_alerts["alerts"][0]["policy"]["policy_code"]
        == "TA_RSI_14_EXTREME"
    )
    assert runtime.saved_alerts["summary"]["policy_count"] == 3
    technical_state = result.update["technical_analysis"]
    assert technical_state["alerts_id"] == "alerts-1"


@pytest.mark.asyncio
async def test_run_alerts_compute_serializes_composite_policy_alert() -> None:
    runtime = _AlertsComputeRuntimeStub()
    runtime.load_indicator_series = _load_alert_indicator_series_oversold  # type: ignore[method-assign]
    runtime.load_pattern_pack = _load_alert_pattern_pack_support_confirmed  # type: ignore[method-assign]
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {
            "indicator_series_id": "series-1",
            "pattern_pack_id": "pattern-1",
        },
    }

    result = await run_alerts_compute_use_case(
        runtime,
        state,
        alert_runtime=AlertRuntimeService(),
    )

    assert result.goto == "regime_compute"
    assert runtime.saved_alerts is not None
    composite_alert = next(
        alert
        for alert in runtime.saved_alerts["alerts"]
        if alert["code"] == "RSI_SUPPORT_REBOUND_SETUP"
    )
    assert composite_alert["policy"]["policy_code"] == "TA_RSI_SUPPORT_REBOUND"
    assert composite_alert["policy"]["lifecycle_state"] == "active"
    assert composite_alert["policy"]["suppression_reason"] is None
    assert len(composite_alert["policy"]["evidence_refs"]) == 2
    assert runtime.saved_alerts["summary"]["lifecycle_counts"]["active"] == 2


@pytest.mark.asyncio
async def test_run_regime_compute_writes_regime_pack_id() -> None:
    runtime = _RegimeComputeRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    result = await run_regime_compute_use_case(
        runtime,
        state,
        regime_runtime=_RegimeRuntimeStub(),
    )

    assert result.goto == "fusion_compute"
    assert runtime.saved_regime_pack is not None
    technical_state = result.update["technical_analysis"]
    assert technical_state["regime_pack_id"] == "regime-1"


@pytest.mark.asyncio
async def test_run_regime_compute_prefers_canonical_feature_and_series_inputs() -> None:
    runtime = _RegimeComputeRuntimeStub(
        feature_pack=TechnicalFeaturePackArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={
                "1d": TechnicalFeatureFrameData(
                    classic_indicators={
                        "ATRP_14": TechnicalFeatureIndicatorData(
                            name="ATRP_14",
                            value=0.018,
                        ),
                        "ADX_14": TechnicalFeatureIndicatorData(
                            name="ADX_14",
                            value=29.4,
                        ),
                    },
                    quant_features={},
                )
            },
        ),
        indicator_series=TechnicalIndicatorSeriesArtifactData(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            timeframes={
                "1d": TechnicalIndicatorSeriesFrameData(
                    timeframe="1d",
                    start="2026-02-01T00:00:00Z",
                    end="2026-02-12T00:00:00Z",
                    series={
                        "ATR_14": {"2026-02-10T00:00:00Z": 1.82},
                        "BB_BANDWIDTH_20": {"2026-02-10T00:00:00Z": 0.071},
                    },
                    timezone="UTC",
                    metadata=None,
                )
            },
        ),
    )
    regime_runtime = _RegimeRuntimeSpy()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {
            "timeseries_bundle_id": "bundle-1",
            "feature_pack_id": "feature-1",
            "indicator_series_id": "series-1",
        },
    }

    await run_regime_compute_use_case(
        runtime,
        state,
        regime_runtime=regime_runtime,
    )

    assert regime_runtime.captured_metadata is not None
    assert (
        regime_runtime.captured_metadata["regime_input_source_atrp_14"]
        == "feature_pack"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_adx_14"] == "feature_pack"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_atr_14"]
        == "indicator_series"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_bb_bandwidth_20"]
        == "indicator_series"
    )


@pytest.mark.asyncio
async def test_run_regime_compute_records_timeseries_fallback_reasons_when_inputs_missing() -> (
    None
):
    runtime = _RegimeComputeRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"timeseries_bundle_id": "bundle-1"},
    }

    await run_regime_compute_use_case(
        runtime,
        state,
        regime_runtime=_RegimeRuntimeStub(),
    )

    assert runtime.saved_regime_pack is not None
    assert runtime.saved_regime_pack["degraded_reasons"] == [
        "1d_REGIME_INPUT_ATR_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_ATRP_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_ADX_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_BB_BANDWIDTH_20_TIMESERIES_COMPUTE",
    ]


@pytest.mark.asyncio
async def test_run_regime_compute_rejects_mismatched_canonical_artifacts() -> None:
    runtime = _RegimeComputeRuntimeStub(
        feature_pack=TechnicalFeaturePackArtifactData(
            ticker="MSFT",
            as_of="2026-02-12T00:00:00Z",
            timeframes={
                "1d": TechnicalFeatureFrameData(
                    classic_indicators={
                        "ATRP_14": TechnicalFeatureIndicatorData(
                            name="ATRP_14",
                            value=0.55,
                        ),
                        "ADX_14": TechnicalFeatureIndicatorData(
                            name="ADX_14",
                            value=99.0,
                        ),
                    },
                    quant_features={},
                )
            },
        ),
        indicator_series=TechnicalIndicatorSeriesArtifactData(
            ticker="AAPL",
            as_of="2026-02-11T00:00:00Z",
            timeframes={
                "1d": TechnicalIndicatorSeriesFrameData(
                    timeframe="1d",
                    start="2026-02-01T00:00:00Z",
                    end="2026-02-12T00:00:00Z",
                    series={
                        "ATR_14": {"2026-02-10T00:00:00Z": 88.0},
                        "BB_BANDWIDTH_20": {"2026-02-10T00:00:00Z": 0.99},
                    },
                    timezone="UTC",
                    metadata=None,
                )
            },
        ),
    )
    regime_runtime = _RegimeRuntimeSpy()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {
            "timeseries_bundle_id": "bundle-1",
            "feature_pack_id": "feature-1",
            "indicator_series_id": "series-1",
        },
    }

    await run_regime_compute_use_case(
        runtime,
        state,
        regime_runtime=regime_runtime,
    )

    assert regime_runtime.captured_metadata is not None
    assert (
        regime_runtime.captured_metadata["regime_input_source_atrp_14"]
        == "timeseries_compute"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_adx_14"]
        == "timeseries_compute"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_atr_14"]
        == "timeseries_compute"
    )
    assert (
        regime_runtime.captured_metadata["regime_input_source_bb_bandwidth_20"]
        == "timeseries_compute"
    )
    assert runtime.saved_regime_pack is not None
    assert runtime.saved_regime_pack["degraded_reasons"] == [
        "REGIME_FEATURE_PACK_CONTEXT_MISMATCH",
        "REGIME_INDICATOR_SERIES_CONTEXT_MISMATCH",
        "1d_REGIME_INPUT_ATR_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_ATRP_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_ADX_14_TIMESERIES_COMPUTE",
        "1d_REGIME_INPUT_BB_BANDWIDTH_20_TIMESERIES_COMPUTE",
    ]


@pytest.mark.asyncio
async def test_run_fusion_compute_handles_pydantic_payloads() -> None:
    runtime = _FusionComputeRuntimeStub()
    state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {
            "feature_pack_id": "feature-1",
            "pattern_pack_id": "pattern-1",
            "regime_pack_id": "regime-1",
            "timeseries_bundle_id": "bundle-1",
        },
    }

    result = await run_fusion_compute_use_case(
        runtime,
        state,
        fusion_runtime=FusionRuntimeService(),
    )

    assert result.goto == "verification_compute"
    assert runtime.saved_fusion_report is not None
    assert (
        runtime.saved_fusion_report["source_artifacts"]["regime_pack_id"] == "regime-1"
    )
    assert runtime.saved_fusion_report["degraded_reasons"] == [
        "1wk_QUANT_SKIPPED",
        "1h_UNAVAILABLE",
    ]
    technical_state = result.update["technical_analysis"]
    assert technical_state["is_degraded"] is True
    assert technical_state["degraded_reasons"] == [
        "1wk_QUANT_SKIPPED",
        "1h_UNAVAILABLE",
    ]


class _InterpretationProviderStub:
    async def generate_interpretation(
        self, _input: TechnicalInterpretationInput
    ) -> TechnicalInterpretationResult:
        return TechnicalInterpretationResult(
            perspective=AnalystPerspectiveModel(
                stance="BULLISH_WATCH",
                stance_summary="Bullish watch with medium risk.",
                rationale_summary="Signals are constructive.",
            ),
        )


@pytest.mark.asyncio
async def test_execute_semantic_pipeline_marks_fusion_degraded_as_semantic_degraded() -> (
    None
):
    projection_artifacts = TechnicalProjectionArtifacts(
        fusion_report=TechnicalFusionReportArtifactData(
            schema_version="1.0",
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            direction="BULLISH_EXTENSION",
            risk_level="medium",
            degraded_reasons=["1h_UNAVAILABLE", "1wk_QUANT_SKIPPED"],
        )
    )
    tags_result = SemanticTagPolicyResult(
        tags=["TREND_ACTIVE"],
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        memory_strength="balanced",
        statistical_state="deviating",
        z_score=1.2,
        confluence=SemanticConfluenceResult(
            bollinger_state="INSIDE",
            statistical_strength=65.0,
            macd_momentum="BULLISH",
            obv_state="NEUTRAL",
        ),
        evidence_list=[],
    )

    with (
        patch(
            "src.agents.technical.application.semantic_pipeline_service.build_semantic_policy_input",
            return_value={},
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.assemble_verification_context",
            return_value=BacktestContextResult(
                backtest_context="",
                wfa_context="",
                price_data=None,
                chart_data=None,
            ),
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.load_projection_artifacts",
            return_value=projection_artifacts,
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.build_interpretation_input",
            return_value=TechnicalInterpretationInput(
                ticker="AAPL",
                direction="BULLISH_EXTENSION",
                risk_level="medium",
                confidence=0.6,
                confidence_calibrated=0.6,
                summary_tags=("TREND_ACTIVE",),
                evidence_items=(),
                momentum_extremes=None,
                setup_context=None,
                validation_context=None,
                diagnostics_context=None,
            ),
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.apply_interpretation_guardrail",
            return_value=type("GuardrailOutcome", (), {"is_aligned": True})(),
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.assemble_semantic_finalize",
            return_value=SemanticFinalizeResult(
                direction="BULLISH_EXTENSION",
                opt_d=0.5,
                raw_data={},
                full_report_data_raw={"ticker": "AAPL"},
                ta_update={"signal": "BULLISH_EXTENSION"},
            ),
        ),
    ):
        result = await execute_semantic_pipeline(
            ticker="AAPL",
            technical_context={},
            assemble_fn=lambda _payload: tags_result,
            interpretation_provider=_InterpretationProviderStub(),
            technical_port=object(),
            verification_report_id=None,
            build_full_report_payload_fn=lambda **_kwargs: {},
        )

    assert result.is_degraded is True
    assert result.degraded_reasons == ("1h_UNAVAILABLE", "1wk_QUANT_SKIPPED")


@pytest.mark.asyncio
async def test_execute_semantic_pipeline_projects_evidence_bundle_into_full_report() -> (
    None
):
    projection_artifacts = TechnicalProjectionArtifacts(
        evidence_bundle=TechnicalEvidenceBundle(
            primary_timeframe="1d",
            support_levels=(180.5, 176.2),
            resistance_levels=(189.0,),
            breakout_signals=(
                EvidenceBreakoutSignalModel(name="BREAKOUT_UP", confidence=0.72),
            ),
            scorecard_summary=EvidenceScorecardSummaryModel(
                timeframe="1d",
                overall_score=0.68,
                classic_label="constructive",
            ),
            regime_summary=RegimeSummaryModel(
                dominant_regime="BULL_TREND",
                timeframe_count=1,
            ),
            structure_confluence_summary=StructureConfluenceSummaryModel(
                timeframe="1d",
                confluence_state="strong",
            ),
            conflict_reasons=("1d:quant_neutral",),
        )
    )
    tags_result = SemanticTagPolicyResult(
        tags=["TREND_ACTIVE"],
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        memory_strength="balanced",
        statistical_state="deviating",
        z_score=1.2,
        confluence=SemanticConfluenceResult(
            bollinger_state="INSIDE",
            statistical_strength=65.0,
            macd_momentum="BULLISH",
            obv_state="NEUTRAL",
        ),
        evidence_list=[],
    )

    with (
        patch(
            "src.agents.technical.application.semantic_pipeline_service.build_semantic_policy_input",
            return_value={},
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.assemble_verification_context",
            return_value=BacktestContextResult(
                backtest_context="",
                wfa_context="",
                price_data=None,
                chart_data=None,
            ),
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.load_projection_artifacts",
            return_value=projection_artifacts,
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.build_interpretation_input",
            return_value=TechnicalInterpretationInput(
                ticker="AAPL",
                direction="BULLISH_EXTENSION",
                risk_level="medium",
                confidence=0.6,
                confidence_calibrated=0.6,
                summary_tags=("TREND_ACTIVE",),
                evidence_items=(),
                momentum_extremes=None,
                setup_context=None,
                validation_context=None,
                diagnostics_context=None,
            ),
        ),
        patch(
            "src.agents.technical.application.semantic_pipeline_service.apply_interpretation_guardrail",
            return_value=type("GuardrailOutcome", (), {"is_aligned": True})(),
        ),
    ):
        result = await execute_semantic_pipeline(
            ticker="AAPL",
            technical_context={},
            assemble_fn=lambda _payload: tags_result,
            interpretation_provider=_InterpretationProviderStub(),
            technical_port=object(),
            verification_report_id=None,
            build_full_report_payload_fn=build_full_report_payload,
        )

    assert (
        result.semantic_finalize_result.full_report_data_raw["evidence_bundle"]
        is not None
    )
    assert (
        result.semantic_finalize_result.full_report_data_raw["evidence_bundle"][
            "primary_timeframe"
        ]
        == "1d"
    )
    assert result.semantic_finalize_result.full_report_data_raw["evidence_bundle"][
        "support_levels"
    ] == [180.5, 176.2]


@dataclass
class _DecisionObservabilityStub:
    event_id: str = "event-1"
    failure: Exception | None = None
    calls: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    async def register_prediction_event(
        self,
        *,
        ticker: str,
        technical_context: JSONObject,
        full_report_payload: JSONObject,
        report_artifact_id: str,
        run_type: str = "workflow",
    ) -> str:
        assert self.calls is not None
        self.calls.append(
            {
                "ticker": ticker,
                "technical_context": technical_context,
                "full_report_payload": full_report_payload,
                "report_artifact_id": report_artifact_id,
                "run_type": run_type,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.event_id


@dataclass
class _FakeSemanticRuntime:
    port: object
    decision_observability: _DecisionObservabilityStub

    def summarize_preview(self, ctx: JSONObject) -> JSONObject:
        return ctx

    def build_semantic_output_artifact(
        self, summary: str, preview: JSONObject, report_id: str
    ) -> dict[str, object]:
        return {
            "kind": "technical_analysis.output",
            "summary": summary,
            "preview": preview,
            "reference": {"artifact_id": report_id},
        }


@pytest.mark.asyncio
async def test_run_semantic_translate_marks_degraded_when_pipeline_degraded() -> None:
    context_state: dict[str, object] = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "technical_analysis": {"optimal_d": 0.5, "z_score_latest": 1.2},
    }
    pipeline_result = SemanticPipelineResult(
        tags_result=SemanticTagPolicyResult(
            tags=["TREND_ACTIVE"],
            direction="BULLISH_EXTENSION",
            risk_level="medium",
            memory_strength="balanced",
            statistical_state="deviating",
            z_score=1.2,
            confluence=SemanticConfluenceResult(
                bollinger_state="INSIDE",
                statistical_strength=65.0,
                macd_momentum="BULLISH",
                obv_state="NEUTRAL",
            ),
            evidence_list=[],
        ),
        analyst_perspective=AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with medium risk.",
            rationale_summary="Fallback interpretation.",
        ),
        backtest_context_result=BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            verification_report=None,
            is_degraded=True,
            failure_code="TECHNICAL_VERIFICATION_CONTEXT_FAILED",
        ),
        semantic_finalize_result=SemanticFinalizeResult(
            direction="BULLISH_EXTENSION",
            opt_d=0.5,
            raw_data={},
            full_report_data_raw={"ticker": "AAPL"},
            ta_update={"signal": "BULLISH_EXTENSION"},
        ),
        llm_is_fallback=True,
        llm_failure_code="TECHNICAL_LLM_INTERPRETATION_FAILED",
        is_degraded=True,
        degraded_reasons=(
            "TECHNICAL_VERIFICATION_CONTEXT_FAILED",
            "TECHNICAL_LLM_INTERPRETATION_FAILED",
        ),
    )

    runtime = _FakeSemanticRuntime(
        port=object(),
        decision_observability=_DecisionObservabilityStub(),
    )

    with (
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.resolve_semantic_translate_context",
            return_value=(
                SemanticTranslateContext(
                    ticker="AAPL",
                    technical_context={"optimal_d": 0.5, "z_score_latest": 1.2},
                    verification_report_id="vr1",
                ),
                None,
            ),
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.execute_semantic_pipeline",
            return_value=pipeline_result,
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.build_semantic_report_update",
            return_value={
                "signal": "BULLISH_EXTENSION",
                "artifact": {"reference": {"artifact_id": "report-1"}},
            },
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.log_event"
        ) as mock_log,
    ):
        result = await run_semantic_translate_use_case(
            runtime,
            context_state,
            assemble_fn=lambda _payload: pipeline_result.tags_result,
            build_full_report_payload_fn=lambda **_kwargs: {},
            interpretation_provider=object(),  # unused due patched execute_semantic_pipeline
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "technical_semantic_translate_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["is_degraded"] is True
    assert fields["artifact_written"] is True
    assert fields["degraded_reason_count"] == 2
    technical_state = result.update["technical_analysis"]
    assert technical_state["is_degraded"] is True
    assert technical_state["degraded_reasons"] == [
        "TECHNICAL_VERIFICATION_CONTEXT_FAILED",
        "TECHNICAL_LLM_INTERPRETATION_FAILED",
    ]


@pytest.mark.asyncio
async def test_run_semantic_translate_registers_prediction_event_after_report_artifact() -> (
    None
):
    runtime = _FakeSemanticRuntime(
        port=object(),
        decision_observability=_DecisionObservabilityStub(event_id="event-42"),
    )
    pipeline_result = SemanticPipelineResult(
        tags_result=SemanticTagPolicyResult(
            tags=["TREND_ACTIVE"],
            direction="BULLISH_EXTENSION",
            risk_level="medium",
            memory_strength="balanced",
            statistical_state="deviating",
            z_score=1.2,
            confluence=SemanticConfluenceResult(
                bollinger_state="INSIDE",
                statistical_strength=65.0,
                macd_momentum="BULLISH",
                obv_state="NEUTRAL",
            ),
            evidence_list=[],
        ),
        analyst_perspective=AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with medium risk.",
            rationale_summary="Fallback interpretation.",
        ),
        backtest_context_result=BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            verification_report=None,
        ),
        semantic_finalize_result=SemanticFinalizeResult(
            direction="BULLISH_EXTENSION",
            opt_d=0.5,
            raw_data={},
            full_report_data_raw={
                "schema_version": "2.0",
                "direction": "BULLISH_EXTENSION",
            },
            ta_update={"signal": "BULLISH_EXTENSION"},
        ),
    )

    with (
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.resolve_semantic_translate_context",
            return_value=(
                SemanticTranslateContext(
                    ticker="AAPL",
                    technical_context={"confidence_calibrated": 0.71},
                    verification_report_id="vr1",
                ),
                None,
            ),
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.execute_semantic_pipeline",
            return_value=pipeline_result,
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.build_semantic_report_update",
            return_value={
                "signal": "BULLISH_EXTENSION",
                "artifact": {"reference": {"artifact_id": "report-1"}},
            },
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.log_event"
        ) as mock_log,
    ):
        result = await run_semantic_translate_use_case(
            runtime,
            {
                "intent_extraction": {"resolved_ticker": "AAPL"},
                "technical_analysis": {"confidence_calibrated": 0.71},
            },
            assemble_fn=lambda _payload: pipeline_result.tags_result,
            build_full_report_payload_fn=lambda **_kwargs: {},
            interpretation_provider=object(),
        )

    assert result.goto == "END"
    assert runtime.decision_observability.calls == [
        {
            "ticker": "AAPL",
            "technical_context": {"confidence_calibrated": 0.71},
            "full_report_payload": {
                "schema_version": "2.0",
                "direction": "BULLISH_EXTENSION",
            },
            "report_artifact_id": "report-1",
            "run_type": "workflow",
        }
    ]
    assert any(
        call.kwargs.get("event") == "technical_prediction_event_written"
        and call.kwargs["fields"]["event_id"] == "event-42"
        for call in mock_log.call_args_list
    )
    assert result.update["technical_analysis"]["is_degraded"] is False


@pytest.mark.asyncio
async def test_run_semantic_translate_degrades_when_prediction_event_write_fails() -> (
    None
):
    runtime = _FakeSemanticRuntime(
        port=object(),
        decision_observability=_DecisionObservabilityStub(
            failure=RuntimeError("db write failed")
        ),
    )
    pipeline_result = SemanticPipelineResult(
        tags_result=SemanticTagPolicyResult(
            tags=["TREND_ACTIVE"],
            direction="BULLISH_EXTENSION",
            risk_level="medium",
            memory_strength="balanced",
            statistical_state="deviating",
            z_score=1.2,
            confluence=SemanticConfluenceResult(
                bollinger_state="INSIDE",
                statistical_strength=65.0,
                macd_momentum="BULLISH",
                obv_state="NEUTRAL",
            ),
            evidence_list=[],
        ),
        analyst_perspective=AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with medium risk.",
            rationale_summary="Fallback interpretation.",
        ),
        backtest_context_result=BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            verification_report=None,
        ),
        semantic_finalize_result=SemanticFinalizeResult(
            direction="BULLISH_EXTENSION",
            opt_d=0.5,
            raw_data={},
            full_report_data_raw={
                "schema_version": "2.0",
                "direction": "BULLISH_EXTENSION",
            },
            ta_update={"signal": "BULLISH_EXTENSION"},
        ),
    )

    with (
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.resolve_semantic_translate_context",
            return_value=(
                SemanticTranslateContext(
                    ticker="AAPL",
                    technical_context={"confidence_calibrated": 0.71},
                    verification_report_id="vr1",
                ),
                None,
            ),
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.execute_semantic_pipeline",
            return_value=pipeline_result,
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.build_semantic_report_update",
            return_value={
                "signal": "BULLISH_EXTENSION",
                "artifact": {"reference": {"artifact_id": "report-1"}},
            },
        ),
        patch(
            "src.agents.technical.application.use_cases.run_semantic_translate_use_case.log_event"
        ) as mock_log,
    ):
        result = await run_semantic_translate_use_case(
            runtime,
            {
                "intent_extraction": {"resolved_ticker": "AAPL"},
                "technical_analysis": {"confidence_calibrated": 0.71},
            },
            assemble_fn=lambda _payload: pipeline_result.tags_result,
            build_full_report_payload_fn=lambda **_kwargs: {},
            interpretation_provider=object(),
        )

    assert result.goto == "END"
    technical_state = result.update["technical_analysis"]
    assert technical_state["is_degraded"] is True
    assert technical_state["degraded_reasons"] == [
        "TECHNICAL_DECISION_EVENT_WRITE_FAILED"
    ]
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "technical_semantic_translate_completed"
    )
    assert completion_call.kwargs["fields"]["degraded_reasons"] == [
        "TECHNICAL_DECISION_EVENT_WRITE_FAILED"
    ]
    assert any(
        call.kwargs.get("event") == "technical_prediction_event_write_failed"
        and call.kwargs.get("error_code") == "TECHNICAL_DECISION_EVENT_WRITE_FAILED"
        for call in mock_log.call_args_list
    )
