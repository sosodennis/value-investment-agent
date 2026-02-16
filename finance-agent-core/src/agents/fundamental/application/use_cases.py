from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.ports import IFundamentalReportRepo
from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.services import (
    build_latest_health_context,
    extract_equity_value_from_metrics,
    resolve_calculator_model_type,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
) -> FundamentalAppContextDTO:
    ticker = resolved_ticker or "UNKNOWN"
    company_name = ticker
    sector: str | None = None
    industry: str | None = None

    profile = intent_ctx.get("company_profile")
    if isinstance(profile, dict):
        name_raw = profile.get("name")
        sector_raw = profile.get("sector")
        industry_raw = profile.get("industry")
        if isinstance(name_raw, str) and name_raw:
            company_name = name_raw
        sector = sector_raw if isinstance(sector_raw, str) else None
        industry = industry_raw if isinstance(industry_raw, str) else None

    return FundamentalAppContextDTO(
        ticker=ticker,
        status=status,
        company_name=company_name,
        sector=sector,
        industry=industry,
        model_type=model_type,
        valuation_summary=valuation_summary,
    )


class _SelectionSignals(Protocol):
    sector: str
    industry: str
    sic: int | None
    revenue_cagr: float | None
    is_profitable: bool | None
    net_income: float | None
    operating_cash_flow: float | None
    total_equity: float | None
    data_coverage: dict[str, bool]


class _SelectionCandidate(Protocol):
    model: _SelectionModel
    score: float
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]


class _SelectionModel(Protocol):
    value: str


class _ModelSelectionLike(Protocol):
    signals: _SelectionSignals
    candidates: Sequence[_SelectionCandidate]


def build_selection_details(selection: _ModelSelectionLike) -> dict[str, object]:
    signals = selection.signals
    candidates = selection.candidates
    return {
        "signals": {
            "sector": signals.sector,
            "industry": signals.industry,
            "sic": signals.sic,
            "revenue_cagr": signals.revenue_cagr,
            "is_profitable": signals.is_profitable,
            "net_income": signals.net_income,
            "operating_cash_flow": signals.operating_cash_flow,
            "total_equity": signals.total_equity,
            "data_coverage": signals.data_coverage,
        },
        "candidates": [
            {
                "model": c.model.value,
                "score": c.score,
                "reasons": list(c.reasons),
                "missing_fields": list(c.missing_fields),
            }
            for c in candidates
        ],
    }


def enrich_reasoning_with_health_context(
    reasoning: str,
    financial_reports: list[FundamentalSelectionReport],
) -> str:
    if not financial_reports:
        return reasoning
    return reasoning + build_latest_health_context(financial_reports)


async def build_and_store_model_selection_artifact(
    *,
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    model_type: str,
    reasoning: str,
    financial_reports: list[JSONObject],
    port: IFundamentalReportRepo,
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    normalize_model_selection_reports_fn: Callable[
        [list[JSONObject]], list[JSONObject]
    ],
    build_model_selection_report_payload_fn: Callable[
        [str, str, str, str, str, str, list[JSONObject]], JSONObject
    ],
    build_model_selection_artifact_fn: Callable[
        [str, str, JSONObject], AgentOutputArtifactPayload
    ],
) -> tuple[AgentOutputArtifactPayload | None, str | None]:
    if not resolved_ticker:
        return None, None

    mapper_ctx = build_mapper_context(
        intent_ctx,
        resolved_ticker,
        status="done",
        model_type=model_type,
        valuation_summary=reasoning,
    )
    normalized_reports = normalize_model_selection_reports_fn(financial_reports)
    preview = summarize_preview(mapper_ctx, normalized_reports)

    full_report_data = build_model_selection_report_payload_fn(
        resolved_ticker,
        model_type,
        mapper_ctx.company_name,
        mapper_ctx.sector or "Unknown",
        mapper_ctx.industry or "Unknown",
        reasoning,
        normalized_reports,
    )

    timestamp = int(time.time())
    report_id = await port.save_financial_reports(
        data=full_report_data,
        produced_by="fundamental_analysis.model_selection",
        key_prefix=f"fa_{resolved_ticker}_{timestamp}",
    )

    artifact = build_model_selection_artifact_fn(resolved_ticker, report_id, preview)
    return artifact, report_id


def build_valuation_missing_inputs_update(
    *,
    fundamental: dict[str, object],
    missing_inputs: list[str],
    assumptions: list[str],
) -> JSONObject:
    fa_update = fundamental.copy()
    fa_update["missing_inputs"] = missing_inputs
    if assumptions:
        fa_update["assumptions"] = assumptions
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
        "error_logs": [
            {
                "node": "calculation",
                "error": f"Missing SEC XBRL inputs: {', '.join(missing_inputs)}",
                "severity": "error",
            }
        ],
    }


def build_valuation_success_update(
    *,
    fundamental: dict[str, object],
    intent_ctx: dict[str, object],
    ticker: str | None,
    model_type: str,
    reports_raw: list[JSONObject],
    reports_artifact_id: str,
    params_dump: JSONObject,
    calculation_metrics: JSONObject,
    assumptions: list[str],
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    build_valuation_artifact_fn: Callable[
        [str | None, str, str, JSONObject], AgentOutputArtifactPayload
    ],
) -> JSONObject:
    fa_update = fundamental.copy()
    fa_update["extraction_output"] = {"params": params_dump}
    fa_update["calculation_output"] = {"metrics": calculation_metrics}
    if assumptions:
        fa_update["assumptions"] = assumptions

    equity_value = extract_equity_value_from_metrics(calculation_metrics)
    app_context = build_mapper_context(
        intent_ctx,
        ticker,
        status="calculated",
        model_type=model_type,
    )
    preview = summarize_preview(app_context, reports_raw)
    preview.update(
        {
            "model_type": model_type,
            "equity_value": equity_value,
            "status": "calculated",
        }
    )
    artifact = build_valuation_artifact_fn(
        ticker, model_type, reports_artifact_id, preview
    )
    fa_update["artifact"] = artifact
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "done"},
        "node_statuses": {"fundamental_analysis": "done"},
        "artifact": artifact,
    }


def build_valuation_error_update(error: str) -> JSONObject:
    return {
        "error_logs": [
            {
                "node": "calculation",
                "error": error,
                "severity": "error",
            }
        ],
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
    }


def resolve_selection_model_type(selected_model_value: str) -> str:
    return resolve_calculator_model_type(selected_model_value)
