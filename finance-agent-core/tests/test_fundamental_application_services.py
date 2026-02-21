from __future__ import annotations

import pytest

from src.agents.fundamental.application.fundamental_service import (
    build_and_store_model_selection_artifact,
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
        reports_raw=[
            {
                "base": {
                    "fiscal_year": {"value": 2025},
                    "period_end_date": {"value": "2025-12-31"},
                }
            }
        ],
        reports_artifact_id="artifact-123",
        params_dump={"wacc": 0.1, "current_price": 39.0},
        calculation_metrics={
            "intrinsic_value": 42.5,
            "equity_value": 4250.0,
            "upside_potential": 0.15,
            "details": {
                "distribution_summary": {
                    "summary": {
                        "percentile_5": 30.0,
                        "median": 42.5,
                        "percentile_95": 60.0,
                    },
                    "diagnostics": {
                        "configured_iterations": 1000,
                        "executed_iterations": 500,
                        "effective_window": 166,
                        "stopped_early": True,
                    },
                }
            },
        },
        assumptions=["wacc defaulted to 10.00%"],
        summarize_preview=lambda _ctx, _reports: {
            "company_name": "GameStop",
            "selected_model": "dcf_standard",
            "assumption_breakdown": _ctx.assumption_breakdown,
            "data_freshness": _ctx.data_freshness,
        },
        build_valuation_artifact_fn=lambda ticker,
        model_type,
        reports_artifact_id,
        preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"估值完成: {ticker or 'UNKNOWN'} ({model_type})",
            "preview": preview,
            "reference": {
                "artifact_id": reports_artifact_id,
                "download_url": f"/api/artifacts/{reports_artifact_id}",
                "type": "financial_reports",
            },
        },
        build_metadata={
            "data_freshness": {
                "market_data": {
                    "provider": "yfinance",
                    "as_of": "2026-02-20T00:00:00Z",
                    "missing_fields": ["target_mean_price"],
                },
                "shares_outstanding_source": "market_data",
            }
        },
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa["extraction_output"]["params"]["wacc"] == 0.1
    assert fa["calculation_output"]["metrics"]["intrinsic_value"] == 42.5
    assert fa["artifact"]["kind"] == "fundamental_analysis.output"
    assert fa["artifact"]["reference"]["artifact_id"] == "artifact-123"
    preview = fa["artifact"]["preview"]
    assert isinstance(preview, dict)
    assert "distribution_summary" in preview
    assert preview["distribution_scenarios"]["base"]["price"] == 42.5
    assert preview["equity_value"] == 4250.0
    assert preview["intrinsic_value"] == 42.5
    assert preview["upside_potential"] == 0.15
    assert preview["assumption_breakdown"]["total_assumptions"] == 1
    assert preview["assumption_breakdown"]["key_parameters"]["current_price"] == 39.0
    assert preview["assumption_breakdown"]["monte_carlo"]["executed_iterations"] == 500
    assert preview["assumption_breakdown"]["monte_carlo"]["effective_window"] == 166
    assert preview["assumption_breakdown"]["monte_carlo"]["stopped_early"] is True
    assert preview["data_freshness"]["financial_statement"]["fiscal_year"] == 2025
    assert preview["data_freshness"]["market_data"]["provider"] == "yfinance"
    assert preview["data_freshness"]["shares_outstanding_source"] == "market_data"
    assert update["node_statuses"]["fundamental_analysis"] == "done"


def test_build_valuation_success_update_keeps_zero_intrinsic_value() -> None:
    update = build_valuation_success_update(
        fundamental={},
        intent_ctx={},
        ticker="GME",
        model_type="dcf_standard",
        reports_raw=[],
        reports_artifact_id="artifact-123",
        params_dump={},
        calculation_metrics={"intrinsic_value": 0.0, "equity_value": 42.5},
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {},
        build_valuation_artifact_fn=lambda ticker,
        model_type,
        reports_artifact_id,
        preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"ok:{ticker}:{model_type}",
            "preview": preview,
            "reference": {
                "artifact_id": reports_artifact_id,
                "download_url": f"/api/artifacts/{reports_artifact_id}",
                "type": "financial_reports",
            },
        },
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    artifact = fa["artifact"]
    assert isinstance(artifact, dict)
    preview = artifact["preview"]
    assert isinstance(preview, dict)
    assert preview["equity_value"] == 42.5
    assert preview["intrinsic_value"] == 0.0


def test_build_valuation_success_update_derives_missing_valuation_metrics() -> None:
    update = build_valuation_success_update(
        fundamental={},
        intent_ctx={},
        ticker="JPM",
        model_type="bank",
        reports_raw=[],
        reports_artifact_id="artifact-derivation",
        params_dump={"shares_outstanding": 100.0, "current_price": 50.0},
        calculation_metrics={"equity_value": "7500"},
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {},
        build_valuation_artifact_fn=lambda ticker,
        model_type,
        reports_artifact_id,
        preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"ok:{ticker}:{model_type}",
            "preview": preview,
            "reference": {
                "artifact_id": reports_artifact_id,
                "download_url": f"/api/artifacts/{reports_artifact_id}",
                "type": "financial_reports",
            },
        },
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    artifact = fa["artifact"]
    assert isinstance(artifact, dict)
    preview = artifact["preview"]
    assert isinstance(preview, dict)
    assert preview["equity_value"] == 7500.0
    assert preview["intrinsic_value"] == 75.0
    assert preview["upside_potential"] == 0.5


def test_build_valuation_success_update_converts_total_distribution_to_per_share() -> (
    None
):
    update = build_valuation_success_update(
        fundamental={},
        intent_ctx={},
        ticker="JPM",
        model_type="bank",
        reports_raw=[],
        reports_artifact_id="artifact-dist-convert",
        params_dump={"shares_outstanding": 100.0, "current_price": 50.0},
        calculation_metrics={
            "details": {
                "distribution_summary": {
                    "metric_type": "equity_value_total",
                    "summary": {
                        "percentile_5": 7000.0,
                        "median": 7500.0,
                        "percentile_95": 8000.0,
                    },
                }
            }
        },
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {},
        build_valuation_artifact_fn=lambda ticker,
        model_type,
        reports_artifact_id,
        preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"ok:{ticker}:{model_type}",
            "preview": preview,
            "reference": {
                "artifact_id": reports_artifact_id,
                "download_url": f"/api/artifacts/{reports_artifact_id}",
                "type": "financial_reports",
            },
        },
    )

    preview = update["fundamental_analysis"]["artifact"]["preview"]
    assert preview["intrinsic_value"] == 75.0
    assert preview["distribution_scenarios"]["bear"]["price"] == 70.0
    assert preview["distribution_scenarios"]["base"]["price"] == 75.0
    assert preview["distribution_scenarios"]["bull"]["price"] == 80.0


def test_build_valuation_success_update_skips_total_distribution_without_shares() -> (
    None
):
    update = build_valuation_success_update(
        fundamental={},
        intent_ctx={},
        ticker="JPM",
        model_type="bank",
        reports_raw=[],
        reports_artifact_id="artifact-dist-missing-shares",
        params_dump={},
        calculation_metrics={
            "details": {
                "distribution_summary": {
                    "metric_type": "equity_value_total",
                    "summary": {
                        "percentile_5": 7000.0,
                        "median": 7500.0,
                        "percentile_95": 8000.0,
                    },
                }
            }
        },
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {},
        build_valuation_artifact_fn=lambda ticker,
        model_type,
        reports_artifact_id,
        preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"ok:{ticker}:{model_type}",
            "preview": preview,
            "reference": {
                "artifact_id": reports_artifact_id,
                "download_url": f"/api/artifacts/{reports_artifact_id}",
                "type": "financial_reports",
            },
        },
    )

    preview = update["fundamental_analysis"]["artifact"]["preview"]
    assert preview.get("distribution_scenarios") is None
    assert preview.get("intrinsic_value") is None


def test_build_valuation_error_update_sets_calculation_error() -> None:
    update = build_valuation_error_update("boom")
    assert update["node_statuses"]["fundamental_analysis"] == "error"
    assert update["internal_progress"]["calculation"] == "error"
    assert update["error_logs"][0]["error"] == "boom"


class _FakeReportRepo:
    async def save_financial_reports(
        self,
        *,
        data: object,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        if not isinstance(data, dict):
            raise TypeError("data must be dict")
        if produced_by != "fundamental_analysis.model_selection":
            raise AssertionError("unexpected producer")
        if key_prefix is None:
            raise AssertionError("missing key_prefix")
        return "report-1"


@pytest.mark.asyncio
async def test_build_and_store_model_selection_artifact_supports_keyword_serializers() -> (
    None
):
    artifact, report_id = await build_and_store_model_selection_artifact(
        intent_ctx={
            "company_profile": {
                "name": "GameStop Corp.",
                "sector": "Consumer Discretionary",
                "industry": "Specialty Retail",
            }
        },
        resolved_ticker="GME",
        model_type="saas",
        reasoning="Model selected",
        financial_reports=[],
        port=_FakeReportRepo(),
        summarize_preview=lambda ctx, _reports: {
            "company_name": ctx.company_name,
            "selected_model": ctx.model_type,
        },
        normalize_model_selection_reports_fn=lambda reports: reports,
        build_model_selection_report_payload_fn=lambda *,
        ticker,
        model_type,
        company_name,
        sector,
        industry,
        reasoning,
        normalized_reports: {
            "ticker": ticker,
            "model_type": model_type,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "status": "done",
        },
        build_model_selection_artifact_fn=lambda *, ticker, report_id, preview: {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": f"基本面分析: {ticker}",
            "preview": preview,
            "reference": {
                "artifact_id": report_id,
                "download_url": f"/api/artifacts/{report_id}",
                "type": "financial_reports",
            },
        },
    )

    assert report_id == "report-1"
    assert artifact is not None
    assert artifact["reference"]["artifact_id"] == "report-1"
    assert artifact["preview"]["company_name"] == "GameStop Corp."
