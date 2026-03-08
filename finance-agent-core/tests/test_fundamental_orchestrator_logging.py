from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from src.agents.fundamental.application.orchestrator import FundamentalOrchestrator
from src.agents.fundamental.application.services.valuation_replay_contracts import (
    INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY,
    VALUATION_REPLAY_SCHEMA_VERSION,
)
from src.agents.fundamental.domain.model_selection import select_valuation_model
from src.agents.fundamental.domain.valuation.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.interface.parsers import parse_financial_health_payload
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


class _FakePort:
    def __init__(self, forward_signals: list[JSONObject] | None = None) -> None:
        self._forward_signals = forward_signals
        self.saved_data: JSONObject | None = None

    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        self.saved_data = data
        _ = (produced_by, key_prefix)
        return "saved-report"

    async def load_financial_reports(
        self, artifact_id: object
    ) -> list[JSONObject] | None:
        _ = artifact_id
        return [{"base": {"fiscal_year": {"value": 2025}}}]

    async def load_financial_reports_bundle(
        self, artifact_id: object
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None:
        _ = artifact_id
        return ([{"base": {"fiscal_year": {"value": 2025}}}], self._forward_signals)


class _FailingSavePort(_FakePort):
    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = (data, produced_by, key_prefix)
        raise RuntimeError("artifact save failed")


class _ValuationParams(BaseModel):
    wacc: float
    terminal_growth: float | None = None
    risk_free_rate: float | None = None
    beta: float | None = None
    market_risk_premium: float | None = None
    growth_rates: list[float] | None = None
    operating_margins: list[float] | None = None
    current_price: float | None = None
    shares_outstanding: float | None = None
    trace_inputs: dict[str, object] = Field(default_factory=dict)


class _AuditResult:
    def __init__(self, passed: bool, messages: list[str] | None = None) -> None:
        self.passed = passed
        self.messages = messages or []


def _build_orchestrator(
    *, forward_signals: list[JSONObject] | None = None
) -> FundamentalOrchestrator:
    def _build_progress_artifact(
        summary: str, preview: JSONObject
    ) -> AgentOutputArtifactPayload:
        return {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": summary,
            "preview": preview,
            "reference": None,
        }

    def _build_model_selection_artifact(
        ticker: str,
        report_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload:
        _ = (ticker, report_id)
        return _build_progress_artifact("model selection", preview)

    def _build_valuation_artifact(
        ticker: str | None,
        model_type: str,
        reports_artifact_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload:
        _ = (ticker, model_type, reports_artifact_id)
        return _build_progress_artifact("valuation", preview)

    return FundamentalOrchestrator(
        port=_FakePort(forward_signals=forward_signals),  # type: ignore[arg-type]
        summarize_preview=lambda _ctx, _reports: {},
        build_progress_artifact=_build_progress_artifact,
        normalize_model_selection_reports=lambda reports: reports,
        build_model_selection_report_payload=lambda *,
        ticker,
        model_type,
        company_name,
        sector,
        industry,
        reasoning,
        normalized_reports,
        forward_signals=None: {
            "ticker": ticker,
            "model_type": model_type,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "forward_signals": forward_signals,
        },
        build_model_selection_artifact=_build_model_selection_artifact,
        build_valuation_artifact=_build_valuation_artifact,
    )


def _build_orchestrator_with_port(port: object) -> FundamentalOrchestrator:
    def _build_progress_artifact(
        summary: str, preview: JSONObject
    ) -> AgentOutputArtifactPayload:
        return {
            "kind": "fundamental_analysis.output",
            "version": "v1",
            "summary": summary,
            "preview": preview,
            "reference": None,
        }

    def _build_model_selection_artifact(
        ticker: str,
        report_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload:
        _ = (ticker, report_id)
        return _build_progress_artifact("model selection", preview)

    def _build_valuation_artifact(
        ticker: str | None,
        model_type: str,
        reports_artifact_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload:
        _ = (ticker, model_type, reports_artifact_id)
        return _build_progress_artifact("valuation", preview)

    return FundamentalOrchestrator(
        port=port,  # type: ignore[arg-type]
        summarize_preview=lambda _ctx, _reports: {},
        build_progress_artifact=_build_progress_artifact,
        normalize_model_selection_reports=lambda reports: reports,
        build_model_selection_report_payload=lambda *,
        ticker,
        model_type,
        company_name,
        sector,
        industry,
        reasoning,
        normalized_reports,
        forward_signals=None: {
            "ticker": ticker,
            "model_type": model_type,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "forward_signals": forward_signals,
        },
        build_model_selection_artifact=_build_model_selection_artifact,
        build_valuation_artifact=_build_valuation_artifact,
    )


def _build_params_result(
    *,
    metadata: JSONObject | None = None,
    assumptions: list[str] | None = None,
    params: JSONObject | None = None,
) -> ParamBuildResult:
    base_params: JSONObject = {"wacc": 0.1}
    if isinstance(params, dict):
        base_params.update(params)
    return ParamBuildResult(
        params=base_params,
        trace_inputs={},
        missing=[],
        assumptions=list(assumptions or []),
        metadata=metadata or {},
    )


def _build_state() -> dict[str, object]:
    return {
        "intent_extraction": {"resolved_ticker": "GOOG"},
        "fundamental_analysis": {
            "model_type": "dcf_growth",
            "financial_reports_artifact_id": "fa-report-1",
        },
    }


def _build_health_state() -> dict[str, object]:
    return {
        "intent_extraction": {
            "resolved_ticker": "AAPL",
            "company_profile": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "sic_code": 3571,
            },
        },
        "fundamental_analysis": {},
    }


@pytest.mark.asyncio
async def test_run_valuation_logs_mc_completion_fields_from_diagnostics() -> None:
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {
            "intrinsic_value": 123.0,
            "details": {
                "distribution_summary": {
                    "summary": {
                        "percentile_5": 101.0,
                        "median": 123.0,
                        "percentile_95": 145.0,
                    },
                    "diagnostics": {
                        "sampler_type": "sobol",
                        "executed_iterations": 300,
                        "corr_diagnostics_available": True,
                        "psd_repaired": True,
                    },
                }
            },
        }

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["sampler_type"] == "sobol"
    assert fields["executed_iterations"] == 300
    assert fields["corr_diagnostics_available"] is True
    assert fields["psd_repaired"] is True
    assert fields["forward_signals_present"] is False
    assert fields["forward_signals_count"] == 0
    assert fields["forward_signals_source"] == "none"


@pytest.mark.asyncio
async def test_run_valuation_logs_mc_completion_defaults_when_diagnostics_missing() -> (
    None
):
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 80.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["sampler_type"] == "disabled"
    assert fields["executed_iterations"] == 0
    assert fields["corr_diagnostics_available"] is False
    assert fields["psd_repaired"] is False
    assert fields["forward_signals_present"] is False
    assert fields["forward_signals_count"] == 0
    assert fields["forward_signals_source"] == "none"


@pytest.mark.asyncio
async def test_run_valuation_logs_forward_signal_completion_fields() -> None:
    orchestrator = _build_orchestrator(
        forward_signals=[
            {
                "signal_id": "sig-1",
                "source_type": "mda",
                "metric": "growth_outlook",
            }
        ]
    )

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 140.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                metadata={
                    "forward_signal": {
                        "signals_total": 1,
                        "source_types": ["mda"],
                    }
                }
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["forward_signals_present"] is True
    assert fields["forward_signals_count"] == 1
    assert fields["forward_signals_source"] == "mda"


@pytest.mark.asyncio
async def test_run_valuation_logs_parameter_source_completion_fields() -> None:
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 125.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                metadata={
                    "data_freshness": {
                        "market_data": {
                            "provider": "yfinance",
                            "as_of": "2026-03-01T00:00:00Z",
                        },
                        "shares_outstanding_source": "filing_market_stale_fallback",
                        "shares_path": {
                            "shares_scope": "filing_consolidated",
                            "equity_value_scope": "mixed_price_filing_shares",
                            "scope_mismatch_detected": True,
                            "scope_mismatch_ratio": 0.53,
                        },
                        "financial_statement": {
                            "filing": {
                                "selection_mode": "latest_available",
                                "filing_date": "2026-02-20",
                            }
                        },
                    },
                    "parameter_source_summary": {
                        "parameters": {
                            "shares_outstanding": {"source": "yfinance"},
                            "risk_free_rate": {"source": "fred"},
                        },
                        "shares_outstanding": {
                            "fallback_reason": "market_stale",
                            "market_is_stale": True,
                            "market_staleness_days": 9,
                            "shares_scope": "filing_consolidated",
                            "equity_value_scope": "mixed_price_filing_shares",
                            "scope_mismatch_detected": True,
                            "scope_mismatch_ratio": 0.53,
                        },
                    },
                }
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["parameter_source_summary_present"] is True
    assert fields["parameter_source_parameter_count"] == 2
    assert fields["shares_fallback_reason"] == "market_stale"
    assert fields["shares_market_is_stale"] is True
    assert fields["shares_market_staleness_days"] == 9
    assert fields["shares_outstanding_source"] == "filing_market_stale_fallback"
    assert fields["shares_scope"] == "filing_consolidated"
    assert fields["equity_value_scope"] == "mixed_price_filing_shares"
    assert fields["shares_scope_mismatch_detected"] is True
    assert fields["shares_scope_mismatch_ratio"] == pytest.approx(0.53)
    assert fields["filing_selection_mode"] == "latest_available"
    key_inputs = fields.get("parameter_source_key_inputs")
    assert isinstance(key_inputs, dict)
    risk_free = key_inputs.get("risk_free_rate")
    assert isinstance(risk_free, dict)
    assert risk_free.get("source") == "fred"
    degrade_reasons = fields.get("degrade_reasons")
    assert isinstance(degrade_reasons, list)
    assert "shares_scope_mismatch" in degrade_reasons


@pytest.mark.asyncio
async def test_run_valuation_does_not_mark_scope_mismatch_degraded_when_resolved() -> (
    None
):
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 125.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                metadata={
                    "data_freshness": {
                        "shares_outstanding_source": "market_data_scope_harmonized",
                    },
                    "parameter_source_summary": {
                        "shares_outstanding": {
                            "shares_scope": "market_class_harmonized",
                            "equity_value_scope": "market_class_harmonized",
                            "scope_mismatch_detected": True,
                            "scope_mismatch_resolved": True,
                            "scope_policy_mode": "harmonize_when_mismatch",
                            "scope_policy_resolution": "harmonized_market_class",
                        }
                    },
                }
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["shares_scope_mismatch_detected"] is True
    assert fields["shares_scope_mismatch_resolved"] is True
    assert fields["shares_scope_policy_resolution"] == "harmonized_market_class"
    assert fields["is_degraded"] is False
    degrade_reasons = fields.get("degrade_reasons")
    assert degrade_reasons is None


@pytest.mark.asyncio
async def test_run_valuation_marks_completion_as_degraded_when_market_data_is_stale() -> (
    None
):
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 125.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                metadata={
                    "data_freshness": {
                        "market_data": {
                            "provider": "yfinance",
                            "as_of": "2026-03-01T00:00:00Z",
                            "quality_flags": [
                                "long_run_growth_anchor:stale",
                                "long_run_growth_anchor:missing_api_key",
                            ],
                        }
                    }
                }
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["is_degraded"] is True
    degrade_reasons = fields.get("degrade_reasons")
    assert isinstance(degrade_reasons, list)
    assert "market_data_quality_flags_present" in degrade_reasons
    assert "market_data_stale" in degrade_reasons
    assert "market_data_missing_api_key" in degrade_reasons


@pytest.mark.asyncio
async def test_run_valuation_marks_completion_as_degraded_when_target_consensus_fallback() -> (
    None
):
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 125.0}

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                metadata={
                    "data_freshness": {
                        "market_data": {
                            "provider": "yfinance",
                            "as_of": "2026-03-01T00:00:00Z",
                            "target_consensus_applied": False,
                            "target_consensus_fallback_reason": "insufficient_sources",
                            "target_consensus_warnings": [
                                "target consensus aggregate skipped: insufficient_sources=1 (<2)"
                            ],
                            "source_warnings": [
                                "tipranks fetch failed: timeout",
                            ],
                        }
                    },
                    "parameter_source_summary": {
                        "market_data_anchor": {
                            "provider": "yfinance",
                            "as_of": "2026-03-01T00:00:00Z",
                            "target_consensus_applied": False,
                            "target_consensus_fallback_reason": "insufficient_sources",
                            "target_consensus_warnings": [
                                "target consensus aggregate skipped: insufficient_sources=1 (<2)"
                            ],
                        },
                        "parameters": {
                            "target_mean_price": {
                                "value": 293.3,
                                "source": "yfinance",
                            }
                        },
                    },
                }
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["target_consensus_applied"] is False
    assert fields["target_consensus_fallback_reason"] == "insufficient_sources"
    assert fields["target_consensus_warnings"] == [
        "target consensus aggregate skipped: insufficient_sources=1 (<2)"
    ]
    assert fields["is_degraded"] is True
    degrade_reasons = fields.get("degrade_reasons")
    assert isinstance(degrade_reasons, list)
    assert "target_consensus_fallback" in degrade_reasons
    assert "target_consensus_fallback:insufficient_sources" in degrade_reasons
    assert "target_consensus_warnings_present" in degrade_reasons
    assert "market_data_source_warnings_present" in degrade_reasons


@pytest.mark.asyncio
async def test_run_valuation_logs_effective_inputs_in_metrics_snapshot() -> None:
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {
            "intrinsic_value": 130.0,
            "equity_value": 130_000.0,
            "upside_potential": -0.2,
            "details": {
                "growth_rates_converged": [0.12, 0.10, 0.08],
                "terminal_growth_effective": 0.0135,
                "sensitivity_summary": {
                    "enabled": True,
                    "scenario_count": 16,
                    "max_upside_delta_pct": 0.22,
                    "max_downside_delta_pct": -0.19,
                    "top_drivers": [
                        {
                            "shock_dimension": "wacc",
                            "shock_value_bp": -100,
                            "delta_pct_vs_base": 0.22,
                        }
                    ],
                },
                "distribution_summary": {
                    "metric_type": "intrinsic_value_per_share",
                    "summary": {
                        "percentile_5": 100.0,
                        "median": 125.0,
                        "percentile_95": 180.0,
                    },
                    "diagnostics": {"base_case_intrinsic_value": 130.0},
                },
            },
        }

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(
                assumptions=[
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
                    "base_reinvestment_guardrail applied "
                    "(version=base_assumption_guardrail_v1_2026_03_05, "
                    "profile=dcf_growth, metric=capex_rates, "
                    "raw_year1=0.420000, raw_yearN=0.420000, "
                    "guarded_year1=0.320000, guarded_yearN=0.160000, "
                    "anchor=0.225000, anchor_samples=2, "
                    "reasons=capex_series_clamped_to_bounds|capex_terminal_converged_to_historical_anchor)",
                    "base_reinvestment_guardrail applied "
                    "(version=base_assumption_guardrail_v1_2026_03_05, "
                    "profile=dcf_growth, metric=wc_rates, "
                    "raw_year1=0.250000, raw_yearN=0.250000, "
                    "guarded_year1=0.140000, guarded_yearN=0.050000, "
                    "anchor=0.110000, anchor_samples=2, "
                    "reasons=wc_series_clamped_to_bounds|wc_terminal_converged_to_historical_anchor)",
                ],
                params={
                    "wacc": 0.091,
                    "terminal_growth": 0.014,
                    "risk_free_rate": 0.0405,
                    "beta": 1.116,
                    "market_risk_premium": 0.045,
                    "growth_rates": [0.12, 0.10, 0.08],
                    "operating_margins": [0.34, 0.33, 0.32],
                    "capex_rates": [0.32, 0.27, 0.16],
                    "wc_rates": [0.14, 0.10, 0.05],
                    "current_price": 162.5,
                    "shares_outstanding": 1_000.0,
                    "model_variant": "dcf_growth",
                },
            ),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    snapshot_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_valuation_metrics_snapshot"
    )
    fields = snapshot_call.kwargs["fields"]
    assert fields["effective_wacc"] == pytest.approx(0.091)
    assert fields["effective_terminal_growth"] == pytest.approx(0.014)
    assert fields["effective_risk_free_rate"] == pytest.approx(0.0405)
    assert fields["effective_beta"] == pytest.approx(1.116)
    assert fields["effective_market_risk_premium"] == pytest.approx(0.045)
    assert fields["effective_wacc_minus_terminal_growth"] == pytest.approx(0.077)
    assert fields["effective_growth_rate_count"] == 3
    assert fields["effective_growth_rate_year1"] == pytest.approx(0.12)
    assert fields["effective_growth_rate_yearN"] == pytest.approx(0.08)
    assert fields["growth_rates_converged"] == pytest.approx([0.12, 0.10, 0.08])
    assert fields["growth_rates_converged_count"] == 3
    assert fields["growth_rates_converged_year1"] == pytest.approx(0.12)
    assert fields["growth_rates_converged_yearN"] == pytest.approx(0.08)
    assert fields["terminal_growth_effective"] == pytest.approx(0.0135)
    assert fields["sensitivity_enabled"] is True
    assert fields["sensitivity_scenario_count"] == 16
    assert fields["sensitivity_max_upside_delta_pct"] == pytest.approx(0.22)
    assert fields["sensitivity_max_downside_delta_pct"] == pytest.approx(-0.19)
    assert fields["sensitivity_top_driver_dimension"] == "wacc"
    assert fields["sensitivity_top_driver_shock_bp"] == -100
    assert fields["sensitivity_top_driver_delta_pct"] == pytest.approx(0.22)
    assert fields["effective_operating_margin_year1"] == pytest.approx(0.34)
    assert fields["effective_operating_margin_yearN"] == pytest.approx(0.32)
    assert fields["growth_consensus_policy"] == "decayed"
    assert fields["growth_consensus_horizon"] == "short_term"
    assert fields["growth_consensus_window_years"] == 3
    assert fields["base_growth_guardrail_applied"] is True
    assert (
        fields["base_growth_guardrail_version"]
        == "base_assumption_guardrail_v1_2026_03_05"
    )
    assert fields["base_growth_raw_year1"] == pytest.approx(0.8)
    assert fields["base_growth_raw_yearN"] == pytest.approx(0.02)
    assert fields["base_growth_guarded_year1"] == pytest.approx(0.55)
    assert fields["base_growth_guarded_yearN"] == pytest.approx(0.014)
    assert fields["base_growth_guardrail_reason_count"] == 2
    assert fields["base_growth_guardrail_reasons"] == [
        "growth_year1_capped",
        "growth_terminal_aligned_to_long_run_target",
    ]
    assert fields["base_margin_guardrail_applied"] is True
    assert (
        fields["base_margin_guardrail_version"]
        == "base_assumption_guardrail_v1_2026_03_05"
    )
    assert fields["base_margin_raw_year1"] == pytest.approx(0.5943)
    assert fields["base_margin_raw_yearN"] == pytest.approx(0.5943)
    assert fields["base_margin_guarded_year1"] == pytest.approx(0.5943)
    assert fields["base_margin_guarded_yearN"] == pytest.approx(0.42)
    assert fields["base_margin_guardrail_reason_count"] == 1
    assert fields["base_margin_guardrail_reasons"] == [
        "margin_terminal_converged_to_normalized_band"
    ]
    assert fields["base_capex_guardrail_applied"] is True
    assert fields["base_capex_guardrail_anchor"] == pytest.approx(0.225)
    assert fields["base_capex_guardrail_anchor_samples"] == 2
    assert fields["base_wc_guardrail_applied"] is True
    assert fields["base_wc_guardrail_anchor"] == pytest.approx(0.11)
    assert fields["base_wc_guardrail_anchor_samples"] == 2
    assert fields["base_guardrail_hit_count"] == 4


@pytest.mark.asyncio
async def test_run_valuation_passes_forward_signals_from_financial_reports_artifact() -> (
    None
):
    orchestrator = _build_orchestrator(
        forward_signals=[{"signal_id": "sig-1", "metric": "growth_outlook"}]
    )
    captured: dict[str, object] = {}

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        return {"intrinsic_value": 77.0}

    await orchestrator.run_valuation(
        _build_state(),
        build_params_fn=lambda _model_type, _ticker, _reports, _forward_signals: (
            captured.update({"forward_signals": _forward_signals})
            or _build_params_result()
        ),
        get_model_runtime_fn=lambda _model_type: {
            "schema": _ValuationParams,
            "calculator": _calculator,
            "auditor": lambda _params: _AuditResult(True, []),
        },
    )

    assert captured["forward_signals"] == [
        {"signal_id": "sig-1", "metric": "growth_outlook"}
    ]


@pytest.mark.asyncio
async def test_run_valuation_stops_on_audit_failure_before_calculator() -> None:
    orchestrator = _build_orchestrator()

    def _calculator(_params: _ValuationParams) -> Mapping[str, object]:
        raise AssertionError("calculator must not run when audit fails")

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
                "auditor": lambda _params: _AuditResult(
                    False,
                    ["FAIL: Terminal growth must be lower than WACC."],
                ),
            },
        )

    assert result.goto == "END"
    error_logs = result.update.get("error_logs")
    assert isinstance(error_logs, list) and error_logs
    first_error = error_logs[0]
    assert isinstance(first_error, Mapping)
    assert "Valuation audit failed" in str(first_error.get("error", ""))

    audit_failed_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "fundamental_valuation_audit_failed"
    )
    assert audit_failed_call.kwargs["fields"]["error"].startswith(
        "Valuation audit failed"
    )


@pytest.mark.asyncio
async def test_run_financial_health_persists_forward_signals_in_financial_reports_artifact() -> (
    None
):
    orchestrator = _build_orchestrator()
    fake_port = orchestrator.port
    assert isinstance(fake_port, _FakePort)

    result = await orchestrator.run_financial_health(
        _build_health_state(),
        fetch_financial_data_fn=lambda _ticker: parse_financial_health_payload(
            {
                "financial_reports": [
                    {
                        "base": {},
                        "industry_type": "Industrial",
                        "extension_type": "Industrial",
                        "extension": {},
                    }
                ],
                "forward_signals": [
                    {
                        "signal_id": "sec_xbrl_growth_2025",
                        "metric": "growth_outlook",
                        "direction": "up",
                        "value": 80.0,
                        "unit": "basis_points",
                        "confidence": 0.62,
                        "source_type": "manual",
                        "evidence": [
                            {
                                "preview_text": "Revenue growth accelerated.",
                                "full_text": "Revenue growth accelerated.",
                                "source_url": "https://www.sec.gov/edgar/search/#/entityName=AAPL",
                            }
                        ],
                    }
                ],
            },
            context="test.financial_health",
        ),
    )

    assert result.goto == "model_selection"
    assert isinstance(fake_port.saved_data, dict)
    assert (
        fake_port.saved_data["forward_signals"][0]["signal_id"]
        == "sec_xbrl_growth_2025"
    )


@pytest.mark.asyncio
async def test_run_valuation_offloads_execution_calculation_to_thread() -> None:
    orchestrator = _build_orchestrator()
    offloaded_calls: list[str] = []

    async def _fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
        name = getattr(func, "__name__", type(func).__name__)
        offloaded_calls.append(str(name))
        return func(*args, **kwargs)  # type: ignore[misc]

    with patch(
        "src.agents.fundamental.application.use_cases.run_valuation_use_case.asyncio.to_thread",
        side_effect=_fake_to_thread,
    ):
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_model_runtime_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": lambda _params: {"intrinsic_value": 123.0},
                "auditor": lambda _params: _AuditResult(True, []),
            },
        )

    assert result.goto == "END"
    assert "execute_valuation_calculation" in offloaded_calls


@pytest.mark.asyncio
async def test_run_valuation_saves_snapshot_and_rewrites_reference() -> None:
    fake_port = _FakePort()
    orchestrator = _build_orchestrator_with_port(fake_port)

    result = await orchestrator.run_valuation(
        _build_state(),
        build_params_fn=lambda _model_type,
        _ticker,
        _reports,
        _forward_signals: _build_params_result(
            params={"terminal_growth": 0.02},
            metadata={
                INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY: {
                    "current_price": 123.45,
                    "consensus_growth_rate": 0.12,
                }
            },
        ),
        get_model_runtime_fn=lambda _model_type: {
            "schema": _ValuationParams,
            "calculator": lambda _params: {"intrinsic_value": 123.0},
            "auditor": lambda _params: _AuditResult(True, []),
        },
    )

    assert result.goto == "END"
    assert isinstance(fake_port.saved_data, dict)
    assert fake_port.saved_data["status"] == "done"
    assert fake_port.saved_data["model_type"] == "dcf_growth"
    assert isinstance(fake_port.saved_data["valuation_diagnostics"], dict)
    assert fake_port.saved_data["valuation_diagnostics"][
        "terminal_growth_effective"
    ] == pytest.approx(0.02)
    assert (
        fake_port.saved_data["replay_schema_version"] == VALUATION_REPLAY_SCHEMA_VERSION
    )
    assert fake_port.saved_data["replay_source_reports_artifact_id"] == "fa-report-1"
    assert fake_port.saved_data["replay_market_snapshot"] == {
        "current_price": 123.45,
        "consensus_growth_rate": 0.12,
    }
    assert isinstance(fake_port.saved_data["replay_params_dump"], dict)
    assert isinstance(fake_port.saved_data["replay_calculation_metrics"], dict)
    assert isinstance(fake_port.saved_data["replay_assumptions"], list)
    assert isinstance(fake_port.saved_data["replay_build_metadata"], dict)

    artifact = result.update["artifact"]
    assert isinstance(artifact, dict)
    assert artifact["reference"]["artifact_id"] == "saved-report"
    assert artifact["reference"]["download_url"] == "/api/artifacts/saved-report"
    assert artifact["reference"]["type"] == "financial_reports"
    assert (
        result.update["fundamental_analysis"]["financial_reports_artifact_id"]
        == "saved-report"
    )


@pytest.mark.asyncio
async def test_run_valuation_keeps_success_when_snapshot_save_fails() -> None:
    orchestrator = _build_orchestrator_with_port(_FailingSavePort())

    result = await orchestrator.run_valuation(
        _build_state(),
        build_params_fn=lambda _model_type,
        _ticker,
        _reports,
        _forward_signals: _build_params_result(),
        get_model_runtime_fn=lambda _model_type: {
            "schema": _ValuationParams,
            "calculator": lambda _params: {"intrinsic_value": 123.0},
            "auditor": lambda _params: _AuditResult(True, []),
        },
    )

    assert result.goto == "END"
    assert result.update["node_statuses"]["fundamental_analysis"] == "done"
    assert (
        result.update["fundamental_analysis"]["financial_reports_artifact_id"]
        == "fa-report-1"
    )


@pytest.mark.asyncio
async def test_run_model_selection_fails_fast_when_reports_artifact_id_missing() -> (
    None
):
    orchestrator = _build_orchestrator_with_port(_FailingSavePort())
    state = _build_health_state()

    with patch(
        "src.agents.fundamental.application.use_cases.run_model_selection_use_case.log_event"
    ) as mock_log:
        result = await orchestrator.run_model_selection(
            state,
            select_valuation_model_fn=select_valuation_model,
        )

    assert result.goto == "END"
    error_logs = result.update.get("error_logs")
    assert isinstance(error_logs, list) and error_logs
    assert "artifact id" in str(error_logs[0].get("error", "")).lower()

    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs.get("event") == "fundamental_model_selection_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["status"] == "error"
    assert fields["error_code"] == "FUNDAMENTAL_MODEL_SELECTION_REPORT_ID_MISSING"
