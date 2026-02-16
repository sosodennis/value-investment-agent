from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from src.agents.fundamental.interface.contracts import (
    FundamentalPreviewInputModel,
    parse_financial_reports_model,
    parse_fundamental_artifact_model,
)
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


class _SelectionSignalsLike(Protocol):
    sector: str
    industry: str
    sic: int | None
    revenue_cagr: float | None
    is_profitable: bool | None
    net_income: float | None
    operating_cash_flow: float | None
    total_equity: float | None
    data_coverage: dict[str, bool]


class _SelectionModelLike(Protocol):
    value: str


class _SelectionCandidateLike(Protocol):
    model: _SelectionModelLike
    score: float
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]


class ModelSelectionLike(Protocol):
    signals: _SelectionSignalsLike
    candidates: Sequence[_SelectionCandidateLike]


def normalize_model_selection_reports(
    financial_reports: list[JSONObject],
) -> list[JSONObject]:
    return parse_financial_reports_model(
        financial_reports, context="model_selection.financial_reports"
    )


def serialize_model_selection_details(selection: ModelSelectionLike) -> JSONObject:
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


def build_model_selection_report_payload(
    *,
    ticker: str,
    model_type: str,
    company_name: str,
    sector: str,
    industry: str,
    reasoning: str,
    normalized_reports: list[JSONObject],
) -> JSONObject:
    return parse_fundamental_artifact_model(
        {
            "ticker": ticker,
            "model_type": model_type,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "reasoning": reasoning,
            "financial_reports": normalized_reports,
            "status": "done",
        }
    )


def build_model_selection_artifact(
    *,
    ticker: str,
    report_id: str,
    preview: JSONObject,
) -> AgentOutputArtifactPayload:
    reference = ArtifactReference(
        artifact_id=report_id,
        download_url=f"/api/artifacts/{report_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"基本面分析: {preview.get('company_name', ticker)} ({preview.get('selected_model')})",
        preview=preview,
        reference=reference,
    )


def build_valuation_preview(
    *,
    ticker: str,
    company_name: str,
    sector: str,
    industry: str,
    status: str,
    valuation_summary: str | None,
    model_type: str,
    reports_raw: list[JSONObject],
    equity_value: float | None,
    summarize_preview: Callable[
        [FundamentalPreviewInputModel, list[JSONObject]], JSONObject
    ],
) -> JSONObject:
    preview_input = FundamentalPreviewInputModel(
        ticker=ticker,
        company_name=company_name,
        sector=sector,
        industry=industry,
        status=status,
        selected_model=model_type,
        model_type=model_type,
        valuation_summary=valuation_summary,
    )
    preview = summarize_preview(preview_input, reports_raw)
    preview.update(
        {
            "model_type": model_type,
            "equity_value": equity_value,
            "status": "calculated",
        }
    )
    return preview


def build_valuation_artifact(
    *,
    ticker: str | None,
    model_type: str,
    reports_artifact_id: str,
    preview: JSONObject,
) -> AgentOutputArtifactPayload:
    reference = ArtifactReference(
        artifact_id=reports_artifact_id,
        download_url=f"/api/artifacts/{reports_artifact_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"估值完成: {ticker or 'UNKNOWN'} ({model_type})",
        preview=preview,
        reference=reference,
    )
