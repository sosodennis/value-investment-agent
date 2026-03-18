from __future__ import annotations

import math
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest

from src.agents.technical.application.fracdiff_runtime_contracts import (
    FracdiffRuntimeResult,
)
from src.agents.technical.application.semantic_finalize_service import (
    assemble_semantic_finalize,
)
from src.agents.technical.application.semantic_interpretation_input_service import (
    build_interpretation_input,
)
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    SemanticFinalizeResult,
    SemanticPipelineResult,
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
from src.agents.technical.domain.shared import FeatureFrame, FeaturePack
from src.agents.technical.interface.contracts import AnalystPerspectiveModel
from src.agents.technical.interface.serializers import build_full_report_payload
from src.agents.technical.subdomains.alerts import AlertRuntimeService
from src.agents.technical.subdomains.features import (
    FeatureRuntimeResult,
    IndicatorSeriesFrameResult,
    IndicatorSeriesRuntimeResult,
)
from src.agents.technical.subdomains.features.domain import (
    serialize_fracdiff_outputs,
)
from src.agents.technical.subdomains.market_data.application.ports import (
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
            conflict_reasons=["1d:quant_neutral"],
            regime_summary={"dominant_regime": "BULL_TREND", "timeframe_count": 1},
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
            feature_summary={
                "classic_count": 0,
                "quant_count": 0,
                "timeframe_count": 1,
            },
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
            metadata={"source_points": 1, "max_points": 1500, "downsample_step": 1},
        )
        return IndicatorSeriesRuntimeResult(
            ticker=getattr(request, "ticker", "AAPL"),
            as_of=getattr(request, "as_of", "2026-02-12T00:00:00Z"),
            timeframes={"1d": frame},
            degraded_reasons=[],
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


@dataclass
class _FusionComputeRuntimeStub:
    saved_fusion_report: JSONObject | None = None

    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        _ = artifact_id
        return None

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
    technical_state = result.update["technical_analysis"]
    assert technical_state["indicator_series_id"] == "series-1"


@pytest.mark.asyncio
async def test_run_alerts_compute_writes_alerts_id() -> None:
    runtime = _AlertsComputeRuntimeStub()
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
    technical_state = result.update["technical_analysis"]
    assert technical_state["alerts_id"] == "alerts-1"


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


@dataclass
class _FakeSemanticRuntime:
    port: object

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

    runtime = _FakeSemanticRuntime(port=object())

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
