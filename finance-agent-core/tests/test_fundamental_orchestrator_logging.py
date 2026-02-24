from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from src.agents.fundamental.application.orchestrator import FundamentalOrchestrator
from src.agents.fundamental.domain.valuation.param_builder import ParamBuildResult
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

    async def load_financial_reports_payload(self, artifact_id: object):
        _ = artifact_id

        class _Report:
            def model_dump(self, mode: str = "json") -> JSONObject:
                _ = mode
                return {"base": {"fiscal_year": {"value": 2025}}}

        class _Payload:
            financial_reports = [_Report()]
            forward_signals = self._forward_signals

        return _Payload()


class _ValuationParams(BaseModel):
    wacc: float
    trace_inputs: dict[str, object] = {}


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


def _build_params_result(*, metadata: JSONObject | None = None) -> ParamBuildResult:
    return ParamBuildResult(
        params={"wacc": 0.1},
        trace_inputs={},
        missing=[],
        assumptions=[],
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

    with patch("src.agents.fundamental.application.orchestrator.log_event") as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_skill_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
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

    with patch("src.agents.fundamental.application.orchestrator.log_event") as mock_log:
        result = await orchestrator.run_valuation(
            _build_state(),
            build_params_fn=lambda _model_type,
            _ticker,
            _reports,
            _forward_signals: _build_params_result(),
            get_skill_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
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

    with patch("src.agents.fundamental.application.orchestrator.log_event") as mock_log:
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
            get_skill_fn=lambda _model_type: {
                "schema": _ValuationParams,
                "calculator": _calculator,
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
        get_skill_fn=lambda _model_type: {
            "schema": _ValuationParams,
            "calculator": _calculator,
        },
    )

    assert captured["forward_signals"] == [
        {"signal_id": "sig-1", "metric": "growth_outlook"}
    ]


@pytest.mark.asyncio
async def test_run_financial_health_persists_forward_signals_in_financial_reports_artifact() -> (
    None
):
    orchestrator = _build_orchestrator()
    fake_port = orchestrator.port
    assert isinstance(fake_port, _FakePort)

    result = await orchestrator.run_financial_health(
        _build_health_state(),
        fetch_financial_data_fn=lambda _ticker: {
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
                            "text_snippet": "Revenue growth accelerated.",
                            "source_url": "https://www.sec.gov/edgar/search/#/entityName=AAPL",
                        }
                    ],
                }
            ],
        },
        normalize_financial_reports_fn=lambda raw, _ctx: raw
        if isinstance(raw, list)
        else [],
    )

    assert result.goto == "model_selection"
    assert isinstance(fake_port.saved_data, dict)
    assert (
        fake_port.saved_data["forward_signals"][0]["signal_id"]
        == "sec_xbrl_growth_2025"
    )
