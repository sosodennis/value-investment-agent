from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

from src.agents.fundamental.data.ports import FundamentalArtifactPort
from src.common.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
)
from src.common.types import AgentOutputArtifactPayload, JSONObject
from src.interface.canonical_serializers import (
    canonicalize_fundamental_artifact_data,
    normalize_financial_reports,
)
from src.interface.schemas import ArtifactReference, build_artifact_payload


def build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
) -> dict[str, object]:
    ticker = resolved_ticker or "UNKNOWN"
    mapper_ctx: dict[str, object] = {
        "ticker": ticker,
        "status": status,
        "company_name": ticker,
    }

    profile = intent_ctx.get("company_profile")
    if isinstance(profile, dict):
        mapper_ctx["company_name"] = profile.get("name")
        mapper_ctx["sector"] = profile.get("sector")
        mapper_ctx["industry"] = profile.get("industry")

    if model_type is not None:
        mapper_ctx["model_type"] = model_type
    if valuation_summary is not None:
        mapper_ctx["valuation_summary"] = valuation_summary

    return mapper_ctx


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
    financial_reports: list[JSONObject],
    *,
    port: FundamentalArtifactPort,
) -> str:
    if not financial_reports:
        return reasoning
    return reasoning + port.build_latest_health_context(financial_reports)


async def build_and_store_model_selection_artifact(
    *,
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    model_type: str,
    reasoning: str,
    financial_reports: list[JSONObject],
    port: FundamentalArtifactPort,
    summarize_preview: Callable[[dict[str, object], list[JSONObject]], JSONObject],
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
    normalized_reports = normalize_financial_reports(
        financial_reports, "model_selection.financial_reports"
    )
    preview = summarize_preview(mapper_ctx, normalized_reports)

    full_report_data = canonicalize_fundamental_artifact_data(
        {
            "ticker": resolved_ticker,
            "model_type": model_type,
            "company_name": mapper_ctx.get("company_name", resolved_ticker),
            "sector": mapper_ctx.get("sector", "Unknown"),
            "industry": mapper_ctx.get("industry", "Unknown"),
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "status": "done",
        }
    )

    timestamp = int(time.time())
    report_id = await port.save_financial_reports(
        data=full_report_data,
        produced_by="fundamental_analysis.model_selection",
        key_prefix=f"fa_{resolved_ticker}_{timestamp}",
    )

    reference = ArtifactReference(
        artifact_id=report_id,
        download_url=f"/api/artifacts/{report_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    artifact = build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"基本面分析: {preview.get('company_name', resolved_ticker)} ({preview.get('selected_model')})",
        preview=preview,
        reference=reference,
    )
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
    summarize_preview: Callable[[dict[str, object], list[JSONObject]], JSONObject],
) -> JSONObject:
    fa_update = fundamental.copy()
    fa_update["extraction_output"] = {"params": params_dump}
    fa_update["calculation_output"] = {"metrics": calculation_metrics}
    if assumptions:
        fa_update["assumptions"] = assumptions

    equity_value = calculation_metrics.get(
        "intrinsic_value"
    ) or calculation_metrics.get("equity_value")
    mapper_ctx = build_mapper_context(
        intent_ctx,
        ticker,
        status="calculated",
        model_type=model_type,
    )
    preview = summarize_preview(mapper_ctx, reports_raw)
    preview.update(
        {
            "model_type": model_type,
            "equity_value": equity_value,
            "status": "calculated",
        }
    )

    reference = ArtifactReference(
        artifact_id=reports_artifact_id,
        download_url=f"/api/artifacts/{reports_artifact_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    artifact = build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"估值完成: {ticker or 'UNKNOWN'} ({model_type})",
        preview=preview,
        reference=reference,
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
