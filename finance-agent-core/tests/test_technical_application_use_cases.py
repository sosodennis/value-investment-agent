from __future__ import annotations

import math

import pandas as pd

from src.agents.technical.application.semantic_service import (
    assemble_semantic_finalize,
)
from src.agents.technical.application.state_updates import (
    build_data_fetch_error_update,
    build_data_fetch_success_update,
    build_fracdiff_error_update,
    build_fracdiff_success_update,
    build_semantic_error_update,
    build_semantic_success_update,
)
from src.agents.technical.data.mappers import serialize_fracdiff_outputs
from src.agents.technical.domain.models import (
    SemanticConfluenceResult,
    SemanticTagPolicyResult,
)
from src.agents.technical.domain.services import (
    derive_memory_strength,
    derive_statistical_state,
    safe_float,
)
from src.agents.technical.interface.serializers import build_full_report_payload
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)


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
    success = build_semantic_success_update({"signal": "bullish"})
    error = build_semantic_error_update("boom")

    assert success.update["current_node"] == "semantic_translate"
    assert success.update["node_statuses"]["technical_analysis"] == "done"
    assert error.update["node_statuses"]["technical_analysis"] == "error"
    assert error.update["error_logs"][0]["error"] == "boom"


def test_data_fetch_update_builders() -> None:
    success = build_data_fetch_success_update(
        price_artifact_id="price-1",
        resolved_ticker="GME",
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
