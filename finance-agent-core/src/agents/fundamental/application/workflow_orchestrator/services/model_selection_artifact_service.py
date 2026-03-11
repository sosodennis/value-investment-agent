from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.context_mapper_service import (
    build_fundamental_app_context,
)
from src.agents.fundamental.application.workflow_orchestrator.dto import (
    FundamentalAppContextDTO,
)
from src.agents.fundamental.application.workflow_orchestrator.ports import (
    IFundamentalReportRepo,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.subdomains.model_selection.domain.entities import (
    FundamentalSelectionReport,
)
from src.agents.fundamental.subdomains.model_selection.domain.financial_health_service import (
    build_latest_health_context,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def _build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
) -> FundamentalAppContextDTO:
    return build_fundamental_app_context(
        intent_ctx,
        resolved_ticker,
        status=status,
        model_type=model_type,
        valuation_summary=valuation_summary,
    )


class _BuildModelSelectionReportPayloadFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        model_type: str,
        company_name: str,
        sector: str,
        industry: str,
        reasoning: str,
        normalized_reports: list[JSONObject],
        forward_signals: list[ForwardSignalPayload] | None = None,
    ) -> JSONObject: ...


class _BuildModelSelectionArtifactFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        report_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload: ...


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
    forward_signals: list[ForwardSignalPayload] | None,
    port: IFundamentalReportRepo,
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    normalize_model_selection_reports_fn: Callable[
        [list[JSONObject]], list[JSONObject]
    ],
    build_model_selection_report_payload_fn: _BuildModelSelectionReportPayloadFn,
    build_model_selection_artifact_fn: _BuildModelSelectionArtifactFn,
) -> tuple[AgentOutputArtifactPayload | None, str | None]:
    if not resolved_ticker:
        return None, None

    mapper_ctx = _build_mapper_context(
        intent_ctx,
        resolved_ticker,
        status="done",
        model_type=model_type,
        valuation_summary=reasoning,
    )
    normalized_reports = normalize_model_selection_reports_fn(financial_reports)
    preview = summarize_preview(mapper_ctx, normalized_reports)

    full_report_data = build_model_selection_report_payload_fn(
        ticker=resolved_ticker,
        model_type=model_type,
        company_name=mapper_ctx.company_name,
        sector=mapper_ctx.sector or "Unknown",
        industry=mapper_ctx.industry or "Unknown",
        reasoning=reasoning,
        normalized_reports=normalized_reports,
        forward_signals=forward_signals,
    )

    timestamp = int(time.time())
    report_id = await port.save_financial_reports(
        data=full_report_data,
        produced_by="fundamental_analysis.model_selection",
        key_prefix=f"fa_{resolved_ticker}_{timestamp}",
    )

    artifact = build_model_selection_artifact_fn(
        ticker=resolved_ticker,
        report_id=report_id,
        preview=preview,
    )
    return artifact, report_id
