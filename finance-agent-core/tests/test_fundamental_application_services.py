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
        reports_raw=[],
        reports_artifact_id="artifact-123",
        params_dump={"wacc": 0.1},
        calculation_metrics={"intrinsic_value": 42.5},
        assumptions=[],
        summarize_preview=lambda _ctx, _reports: {
            "company_name": "GameStop",
            "selected_model": "dcf_standard",
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
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa["extraction_output"]["params"]["wacc"] == 0.1
    assert fa["calculation_output"]["metrics"]["intrinsic_value"] == 42.5
    assert fa["artifact"]["kind"] == "fundamental_analysis.output"
    assert fa["artifact"]["reference"]["artifact_id"] == "artifact-123"
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
    assert preview["equity_value"] == 0.0


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
