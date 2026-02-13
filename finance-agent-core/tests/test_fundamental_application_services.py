from __future__ import annotations

from src.agents.fundamental.application.use_cases import (
    build_valuation_error_update,
    build_valuation_missing_inputs_update,
    build_valuation_success_update,
)


def test_build_valuation_missing_inputs_update_sets_error_shape() -> None:
    update = build_valuation_missing_inputs_update(
        fundamental={},
        missing_inputs=["wacc", "terminal_growth_rate"],
        assumptions=["assume_wacc_from_sector"],
    )
    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa["missing_inputs"] == ["wacc", "terminal_growth_rate"]
    assert fa["assumptions"] == ["assume_wacc_from_sector"]
    assert update["node_statuses"]["fundamental_analysis"] == "error"
    assert "Missing SEC XBRL inputs" in update["error_logs"][0]["error"]


def test_build_valuation_success_update_includes_output_and_artifact() -> None:
    update = build_valuation_success_update(
        fundamental={},
        intent_ctx={},
        ticker="GME",
        model_type="dcf_standard",
        reports_raw=[],
        reports_artifact_id="artifact-123",
        params_dump={"wacc": 0.1},
        calculation_metrics={"intrinsic_value": 42.5},
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {
            "company_name": "GameStop",
            "selected_model": "dcf_standard",
        },
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa["extraction_output"]["params"]["wacc"] == 0.1
    assert fa["calculation_output"]["metrics"]["intrinsic_value"] == 42.5
    assert fa["artifact"]["kind"] == "fundamental_analysis.output"
    assert fa["artifact"]["reference"]["artifact_id"] == "artifact-123"
    assert update["node_statuses"]["fundamental_analysis"] == "done"


def test_build_valuation_error_update_sets_calculation_error() -> None:
    update = build_valuation_error_update("boom")
    assert update["node_statuses"]["fundamental_analysis"] == "error"
    assert update["internal_progress"]["calculation"] == "error"
    assert update["error_logs"][0]["error"] == "boom"
