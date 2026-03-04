from __future__ import annotations

import math
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest

from src.agents.technical.application.fracdiff_runtime_contracts import (
    FracdiffRuntimeResult,
)
from src.agents.technical.application.ports import (
    TechnicalOhlcvFetchResult,
    TechnicalProviderFailure,
)
from src.agents.technical.application.semantic_finalize_service import (
    assemble_semantic_finalize,
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
from src.agents.technical.application.use_cases.run_data_fetch_use_case import (
    run_data_fetch_use_case,
)
from src.agents.technical.application.use_cases.run_fracdiff_compute_use_case import (
    run_fracdiff_compute_use_case,
)
from src.agents.technical.application.use_cases.run_semantic_translate_use_case import (
    run_semantic_translate_use_case,
)
from src.agents.technical.domain.fracdiff.serialization_service import (
    serialize_fracdiff_outputs,
)
from src.agents.technical.domain.signal_policy import (
    SemanticConfluenceResult,
    SemanticTagPolicyResult,
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)
from src.agents.technical.interface.serializers import build_full_report_payload
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
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
        },
        tags_dict={"direction": "bullish", "risk_level": "MEDIUM", "tags": ["A", "B"]},
        llm_interpretation="Interpretation",
        raw_data={"price_series": {"2025-01-01": 1.0}},
    )

    frac_metrics = payload["frac_diff_metrics"]
    signal_state = payload["signal_state"]

    assert frac_metrics["memory_strength"] == "fragile"
    assert signal_state["statistical_state"] == "anomaly"
    assert signal_state["direction"] == "BULLISH"
    assert derive_memory_strength(0.2) == "structurally_stable"
    assert derive_statistical_state(0.2) == "equilibrium"


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
        llm_interpretation="Some interpretation",
        price_data=price_data,
        chart_data=chart_data,
        build_full_report_payload_fn=build_full_report_payload,
    )

    assert result.direction == "BULLISH"
    assert result.ta_update["signal"] == "bullish"
    assert result.ta_update["memory_strength"] == "balanced"
    assert result.raw_data["price_series"]["2025-01-01"] == 10.0
    assert (
        result.full_report_data_raw["signal_state"]["statistical_state"] == "deviating"
    )


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
    def fetch_daily_ohlcv(
        self, ticker_symbol: str, period: str = "5y"
    ) -> TechnicalOhlcvFetchResult:
        _ = (ticker_symbol, period)
        return TechnicalOhlcvFetchResult(
            data=None,
            failure=TechnicalProviderFailure(
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
    assert "TECHNICAL_OHLCV_FETCH_FAILED" in result.update["error_logs"][0]["error"]


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
        llm_interpretation="fallback interpretation",
        backtest_context_result=BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            is_degraded=True,
            failure_code="TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED",
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
            "TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED",
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
                    price_artifact_id="p1",
                    chart_artifact_id="c1",
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
            fracdiff_runtime=object(),  # unused due patched execute_semantic_pipeline
            market_data_provider=object(),  # unused due patched execute_semantic_pipeline
            interpretation_provider=object(),  # unused due patched execute_semantic_pipeline
            backtest_runtime=object(),  # unused due patched execute_semantic_pipeline
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
        "TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED",
        "TECHNICAL_LLM_INTERPRETATION_FAILED",
    ]
