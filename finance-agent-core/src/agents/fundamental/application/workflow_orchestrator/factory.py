from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
)
from src.agents.fundamental.application.workflow_orchestrator.dto import (
    FundamentalAppContextDTO,
)
from src.agents.fundamental.application.workflow_orchestrator.orchestrator import (
    FundamentalNodeResult,
    FundamentalOrchestrator,
)
from src.agents.fundamental.application.workflow_orchestrator.ports import (
    FundamentalFinancialStatementsPayload,
    IFundamentalFinancialStatementsProvider,
    IFundamentalForwardSignalsProvider,
)
from src.agents.fundamental.capabilities.artifacts_provenance.public import (
    IFundamentalReportRepo,
)
from src.agents.fundamental.capabilities.financial_statements.public import (
    parse_financial_statements_payload,
)
from src.agents.fundamental.capabilities.model_selection.public import (
    select_valuation_model,
)
from src.agents.fundamental.interface.workflow_orchestrator.contracts import (
    FundamentalPreviewInputModel,
)
from src.agents.fundamental.interface.workflow_orchestrator.mappers import (
    summarize_fundamental_for_preview,
)
from src.agents.fundamental.interface.workflow_orchestrator.serializers import (
    build_model_selection_artifact,
    build_model_selection_report_payload,
    build_valuation_artifact,
    normalize_model_selection_reports,
)
from src.artifacts.public import (
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
    build_artifact_payload,
)


def _summarize_preview(
    ctx: FundamentalAppContextDTO, reports: list[dict[str, object]] | None
) -> dict[str, object]:
    return summarize_fundamental_for_preview(
        FundamentalPreviewInputModel(
            ticker=ctx.ticker,
            company_name=ctx.company_name,
            sector=ctx.sector or "Unknown",
            industry=ctx.industry or "Unknown",
            status=ctx.status,
            selected_model=ctx.model_type,
            model_type=ctx.model_type,
            valuation_summary=ctx.valuation_summary,
            assumption_breakdown=ctx.assumption_breakdown,
            data_freshness=ctx.data_freshness,
            assumption_risk_level=ctx.assumption_risk_level,
            data_quality_flags=ctx.data_quality_flags,
            time_alignment_status=ctx.time_alignment_status,
            forward_signal_summary=ctx.forward_signal_summary,
            forward_signal_risk_level=ctx.forward_signal_risk_level,
            forward_signal_evidence_count=ctx.forward_signal_evidence_count,
        ),
        reports,
    )


def _build_progress_artifact(
    summary: str, preview: dict[str, object]
) -> dict[str, object]:
    return build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=summary,
        preview=preview,
        reference=None,
    )


def build_fundamental_orchestrator(
    *,
    port: IFundamentalReportRepo,
) -> FundamentalOrchestrator:
    return FundamentalOrchestrator(
        port=port,
        summarize_preview=_summarize_preview,
        build_progress_artifact=_build_progress_artifact,
        normalize_model_selection_reports=normalize_model_selection_reports,
        build_model_selection_report_payload=build_model_selection_report_payload,
        build_model_selection_artifact=build_model_selection_artifact,
        build_valuation_artifact=build_valuation_artifact,
    )


@dataclass(frozen=True)
class FundamentalWorkflowRunner:
    orchestrator: FundamentalOrchestrator
    fetch_financial_reports_fn: IFundamentalFinancialStatementsProvider
    extract_forward_signals_fn: IFundamentalForwardSignalsProvider
    fundamental_service_client: FundamentalServiceClient
    service_timeout_seconds: float = 10.0
    financial_payload_years: int = 5

    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        def _fetch_and_parse_financial_statements_payload(
            ticker: str,
        ):
            payload: FundamentalFinancialStatementsPayload = (
                self.fetch_financial_reports_fn(
                    ticker, years=self.financial_payload_years
                )
            )
            return parse_financial_statements_payload(
                payload,
                context="financial_health.payload",
            )

        return await self.orchestrator.run_financial_health(
            state,
            fetch_financial_reports_fn=_fetch_and_parse_financial_statements_payload,
            extract_forward_signals_fn=lambda ticker, reports_raw: (
                self.extract_forward_signals_fn(
                    ticker=ticker,
                    reports_raw=reports_raw,
                )
            ),
        )

    async def run_model_selection(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_model_selection(
            state,
            select_valuation_model_fn=select_valuation_model,
        )

    async def run_valuation(
        self,
        state: Mapping[str, object],
        *,
        request_approval: Callable[[Mapping[str, object]], object],
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_service_valuation(
            state,
            client=self.fundamental_service_client,
            request_approval_fn=lambda payload: request_approval(payload),
            timeout_seconds=self.service_timeout_seconds,
        )


def build_fundamental_workflow_runner(
    *,
    orchestrator: FundamentalOrchestrator,
    fetch_financial_reports_fn: IFundamentalFinancialStatementsProvider,
    extract_forward_signals_fn: IFundamentalForwardSignalsProvider,
    fundamental_service_client: FundamentalServiceClient,
    service_timeout_seconds: float = 10.0,
    financial_payload_years: int = 5,
) -> FundamentalWorkflowRunner:
    return FundamentalWorkflowRunner(
        orchestrator=orchestrator,
        fetch_financial_reports_fn=fetch_financial_reports_fn,
        extract_forward_signals_fn=extract_forward_signals_fn,
        fundamental_service_client=fundamental_service_client,
        service_timeout_seconds=service_timeout_seconds,
        financial_payload_years=financial_payload_years,
    )
