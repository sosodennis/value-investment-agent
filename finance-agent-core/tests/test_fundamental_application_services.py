from __future__ import annotations

import pytest

from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalEvidence,
    ForwardSignalPayload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.serializers import (
    serialize_forward_signals,
)
from src.agents.fundamental.workflow_orchestrator.application.services.model_selection_artifact_service import (
    build_and_store_model_selection_artifact,
)
from src.agents.fundamental.workflow_orchestrator.application.services.valuation_update_service import (
    build_valuation_error_update,
    build_valuation_missing_inputs_update,
    build_valuation_success_update,
)


def _build_forward_signal(
    *,
    signal_id: str = "sig-1",
    source_type: str = "mda",
) -> ForwardSignalPayload:
    return ForwardSignalPayload(
        signal_id=signal_id,
        source_type=source_type,
        metric="growth_outlook",
        direction="up",
        value=120.0,
        unit="basis_points",
        confidence=0.72,
        as_of="2026-03-10T00:00:00Z",
        evidence=[
            ForwardSignalEvidence(
                preview_text="Guidance raised.",
                full_text="Guidance raised with stronger outlook.",
                source_url="https://www.sec.gov/edgar/search/?q=GME",
            )
        ],
    )


def test_build_valuation_missing_inputs_update_sets_error_shape() -> None:
    update = build_valuation_missing_inputs_update(
        fundamental={},
        missing_inputs=["wacc", "terminal_growth_rate"],
        assumptions=["assume_wacc_from_sector"],
    )
    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa == {}
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
                "growth_rates_converged": [0.12, 0.10, 0.08],
                "terminal_growth_effective": 0.0135,
                "sensitivity_summary": {
                    "enabled": True,
                    "scenario_count": 16,
                    "max_upside_delta_pct": 0.22,
                    "max_downside_delta_pct": -0.18,
                    "top_drivers": [
                        {
                            "shock_dimension": "wacc",
                            "shock_value_bp": -100,
                            "delta_pct_vs_base": 0.22,
                        }
                    ],
                },
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
                        "psd_repaired": True,
                        "psd_repaired_groups": 1,
                        "psd_min_eigen_before": -0.12,
                        "psd_min_eigen_after": 1e-8,
                        "corr_diagnostics_available": True,
                        "corr_pairs_total": 1,
                        "corr_pearson_max_abs_error": 0.03,
                        "corr_spearman_max_abs_error": 0.02,
                    },
                },
            },
        },
        assumptions=[
            "wacc defaulted to 10.00%",
            "consensus_growth_rate decayed into near-term DCF growth path "
            "(horizon=short_term, window_years=3, weights=1.00|0.67|0.33)",
            "base_growth_guardrail applied "
            "(version=base_assumption_guardrail_v1_2026_03_05, "
            "raw_year1=0.800000, raw_yearN=0.020000, "
            "guarded_year1=0.550000, guarded_yearN=0.014000, "
            "reasons=growth_year1_capped|growth_terminal_aligned_to_long_run_target)",
            "base_margin_guardrail applied "
            "(version=base_assumption_guardrail_v1_2026_03_05, "
            "raw_year1=0.594300, raw_yearN=0.594300, "
            "guarded_year1=0.594300, guarded_yearN=0.420000, "
            "reasons=margin_terminal_converged_to_normalized_band)",
        ],
        summarize_preview=lambda _ctx, _reports: {
            "company_name": "GameStop",
            "selected_model": "dcf_standard",
            "assumption_breakdown": _ctx.assumption_breakdown,
            "data_freshness": _ctx.data_freshness,
            "forward_signal_summary": _ctx.forward_signal_summary,
            "forward_signal_risk_level": _ctx.forward_signal_risk_level,
            "forward_signal_evidence_count": _ctx.forward_signal_evidence_count,
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
            "forward_signal": {
                "signals_total": 2,
                "signals_accepted": 1,
                "signals_rejected": 1,
                "evidence_count": 3,
                "growth_adjustment_basis_points": 45.0,
                "margin_adjustment_basis_points": -20.0,
                "calibration_applied": True,
                "mapping_version": "forward_signal_calibration_v2_2026_03_05",
                "risk_level": "medium",
                "source_types": ["mda", "manual"],
                "decisions": [
                    {
                        "signal_id": "sig-1",
                        "metric": "growth_outlook",
                        "accepted": True,
                        "reason": "accepted",
                        "effective_basis_points": 45.0,
                    }
                ],
            },
            "data_freshness": {
                "financial_statement": {
                    "fiscal_year": 2025,
                    "period_end_date": "2025-12-31",
                    "filing": {
                        "form": "10-K",
                        "filing_date": "2026-02-20",
                        "selection_mode": "latest_available",
                        "matched_fiscal_year": 2025,
                    },
                },
                "market_data": {
                    "provider": "yfinance",
                    "as_of": "2026-02-20T00:00:00Z",
                    "missing_fields": ["target_mean_price"],
                    "quality_flags": ["risk_free_rate:defaulted"],
                    "license_note": "test license note",
                    "market_datums": {
                        "risk_free_rate": {
                            "value": 0.042,
                            "source": "policy_default",
                            "as_of": "2026-02-20T00:00:00Z",
                            "quality_flags": ["defaulted"],
                            "license_note": "internal default",
                        }
                    },
                },
                "shares_outstanding_source": "market_data",
                "time_alignment": {
                    "status": "high_risk",
                    "policy": "warn",
                    "lag_days": 420,
                    "threshold_days": 365,
                    "market_as_of": "2026-02-20T00:00:00+00:00",
                    "filing_period_end": "2024-12-31",
                },
            },
            "parameter_source_summary": {
                "market_data_anchor": {
                    "provider": "yfinance",
                    "as_of": "2026-02-20T00:00:00Z",
                },
                "shares_outstanding": {
                    "selected_source": "market_data",
                    "market_is_stale": False,
                },
            },
        },
    )

    fa = update["fundamental_analysis"]
    assert isinstance(fa, dict)
    assert fa["artifact"]["kind"] == "fundamental_analysis.output"
    assert fa["artifact"]["reference"]["artifact_id"] == "artifact-123"
    preview = fa["artifact"]["preview"]
    assert isinstance(preview, dict)
    assert "distribution_summary" in preview
    assert preview["distribution_scenarios"]["base"]["price"] == 42.5
    assert preview["valuation_diagnostics"]["growth_rates_converged"] == pytest.approx(
        [0.12, 0.10, 0.08]
    )
    assert preview["valuation_diagnostics"][
        "terminal_growth_effective"
    ] == pytest.approx(0.0135)
    assert (
        preview["valuation_diagnostics"]["forward_signal_mapping_version"]
        == "forward_signal_calibration_v2_2026_03_05"
    )
    assert (
        preview["valuation_diagnostics"]["forward_signal_calibration_applied"] is True
    )
    assert preview["valuation_diagnostics"]["base_growth_guardrail_applied"] is True
    assert preview["valuation_diagnostics"]["growth_consensus_policy"] == "decayed"
    assert preview["valuation_diagnostics"]["growth_consensus_horizon"] == "short_term"
    assert preview["valuation_diagnostics"]["growth_consensus_window_years"] == 3
    assert (
        preview["valuation_diagnostics"]["base_growth_guardrail_version"]
        == "base_assumption_guardrail_v1_2026_03_05"
    )
    assert preview["valuation_diagnostics"]["base_growth_raw_year1"] == pytest.approx(
        0.8
    )
    assert preview["valuation_diagnostics"]["base_growth_raw_yearN"] == pytest.approx(
        0.02
    )
    assert preview["valuation_diagnostics"][
        "base_growth_guarded_year1"
    ] == pytest.approx(0.55)
    assert preview["valuation_diagnostics"][
        "base_growth_guarded_yearN"
    ] == pytest.approx(0.014)
    assert preview["valuation_diagnostics"]["base_growth_guardrail_reason_count"] == 2
    assert preview["valuation_diagnostics"]["base_growth_guardrail_reasons"] == [
        "growth_year1_capped",
        "growth_terminal_aligned_to_long_run_target",
    ]
    assert preview["valuation_diagnostics"]["base_margin_guardrail_applied"] is True
    assert (
        preview["valuation_diagnostics"]["base_margin_guardrail_version"]
        == "base_assumption_guardrail_v1_2026_03_05"
    )
    assert preview["valuation_diagnostics"]["base_margin_raw_year1"] == pytest.approx(
        0.5943
    )
    assert preview["valuation_diagnostics"]["base_margin_raw_yearN"] == pytest.approx(
        0.5943
    )
    assert preview["valuation_diagnostics"][
        "base_margin_guarded_year1"
    ] == pytest.approx(0.5943)
    assert preview["valuation_diagnostics"][
        "base_margin_guarded_yearN"
    ] == pytest.approx(0.42)
    assert preview["valuation_diagnostics"]["base_margin_guardrail_reason_count"] == 1
    assert preview["valuation_diagnostics"]["base_margin_guardrail_reasons"] == [
        "margin_terminal_converged_to_normalized_band"
    ]
    assert preview["valuation_diagnostics"]["base_guardrail_hit_count"] == 2
    assert preview["valuation_diagnostics"]["sensitivity_summary"]["enabled"] is True
    assert (
        preview["valuation_diagnostics"]["sensitivity_summary"]["scenario_count"] == 16
    )
    assert preview["valuation_diagnostics"]["sensitivity_summary"][
        "max_upside_delta_pct"
    ] == pytest.approx(0.22)
    assert preview["equity_value"] == 4250.0
    assert preview["intrinsic_value"] == 42.5
    assert preview["upside_potential"] == 0.15
    assert preview["assumption_breakdown"]["total_assumptions"] == 4
    assert preview["assumption_breakdown"]["key_parameters"]["current_price"] == 39.0
    assert (
        preview["assumption_breakdown"]["key_parameters"]["time_alignment_status"]
        == "high_risk"
    )
    assert (
        preview["assumption_breakdown"]["key_parameters"]["time_alignment_lag_days"]
        == 420
    )
    assert preview["assumption_breakdown"]["monte_carlo"]["executed_iterations"] == 500
    assert preview["assumption_breakdown"]["monte_carlo"]["effective_window"] == 166
    assert preview["assumption_breakdown"]["monte_carlo"]["stopped_early"] is True
    assert preview["assumption_breakdown"]["monte_carlo"]["psd_repaired"] is True
    assert preview["assumption_breakdown"]["monte_carlo"]["psd_repaired_groups"] == 1
    assert (
        preview["assumption_breakdown"]["monte_carlo"]["corr_diagnostics_available"]
        is True
    )
    assert preview["assumption_breakdown"]["monte_carlo"]["corr_pairs_total"] == 1
    assert preview["assumption_breakdown"]["sensitivity"]["enabled"] is True
    assert preview["assumption_breakdown"]["sensitivity"]["scenario_count"] == 16
    assert (
        preview["assumption_breakdown"]["sensitivity"]["top_drivers"][0][
            "shock_dimension"
        ]
        == "wacc"
    )
    assert preview["assumption_risk_level"] == "high"
    assert preview["data_quality_flags"] == [
        "defaults_present",
        "market_data_missing:target_mean_price",
        "market_data_quality:risk_free_rate:defaulted",
        "time_alignment:high_risk",
    ]
    assert preview["time_alignment_status"] == "high_risk"
    assert preview["forward_signal_summary"]["signals_total"] == 2
    assert preview["forward_signal_risk_level"] == "medium"
    assert preview["forward_signal_evidence_count"] == 3
    assert preview["parameter_source_summary"]["market_data_anchor"]["provider"] == (
        "yfinance"
    )
    assert preview["forward_signal_summary"]["source_types"] == ["mda", "manual"]
    assert (
        preview["assumption_breakdown"]["forward_signal_summary"][
            "growth_adjustment_basis_points"
        ]
        == 45.0
    )
    assert (
        preview["assumption_breakdown"]["parameter_source_summary"][
            "shares_outstanding"
        ]["selected_source"]
        == "market_data"
    )
    assert (
        preview["assumption_breakdown"]["base_assumption_guardrail"]["version"]
        == "base_assumption_guardrail_v1_2026_03_05"
    )
    assert preview["assumption_breakdown"]["base_assumption_guardrail"]["growth"][
        "guarded_year1"
    ] == pytest.approx(0.55)
    assert (
        preview["assumption_breakdown"]["base_assumption_guardrail"]["growth"][
            "reason_count"
        ]
        == 2
    )
    assert preview["assumption_breakdown"]["base_assumption_guardrail"]["margin"][
        "guarded_yearN"
    ] == pytest.approx(0.42)
    assert (
        preview["assumption_breakdown"]["base_assumption_guardrail"]["margin"][
            "reason_count"
        ]
        == 1
    )
    assert preview["data_freshness"]["financial_statement"]["fiscal_year"] == 2025
    assert (
        preview["data_freshness"]["financial_statement"]["filing"]["selection_mode"]
        == "latest_available"
    )
    assert preview["data_freshness"]["market_data"]["provider"] == "yfinance"
    assert preview["data_freshness"]["market_data"]["quality_flags"] == [
        "risk_free_rate:defaulted"
    ]
    assert (
        preview["data_freshness"]["market_data"]["license_note"] == "test license note"
    )
    assert (
        preview["data_freshness"]["market_data"]["market_datums"]["risk_free_rate"][
            "source"
        ]
        == "policy_default"
    )
    assert preview["data_freshness"]["shares_outstanding_source"] == "market_data"
    assert preview["data_freshness"]["time_alignment"]["status"] == "high_risk"
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
    def __init__(self) -> None:
        self.saved_data: dict[str, object] | None = None

    async def save_financial_reports(
        self,
        *,
        data: object,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        if not isinstance(data, dict):
            raise TypeError("data must be dict")
        self.saved_data = data
        if produced_by != "fundamental_analysis.model_selection":
            raise AssertionError("unexpected producer")
        if key_prefix is None:
            raise AssertionError("missing key_prefix")
        return "report-1"


@pytest.mark.asyncio
async def test_build_and_store_model_selection_artifact_supports_keyword_serializers() -> (
    None
):
    repo = _FakeReportRepo()
    forward_signals = [_build_forward_signal()]
    expected_forward_signals = serialize_forward_signals(forward_signals)
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
        forward_signals=forward_signals,
        port=repo,
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
        forward_signals,
        normalized_reports: {
            "ticker": ticker,
            "model_type": model_type,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "forward_signals": serialize_forward_signals(forward_signals),
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
    assert isinstance(repo.saved_data, dict)
    assert repo.saved_data["forward_signals"] == expected_forward_signals
