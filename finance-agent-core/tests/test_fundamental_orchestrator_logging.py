from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from src.agents.fundamental.application.orchestrator import FundamentalOrchestrator
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
    trace_inputs: dict[str, object] = {}


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
) -> ParamBuildResult:
    return ParamBuildResult(
        params={"wacc": 0.1},
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
    assert fields["filing_selection_mode"] == "latest_available"


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
                            "quality_flags": ["long_run_growth_anchor:stale"],
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
