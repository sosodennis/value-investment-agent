from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.core_valuation.domain.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.core_valuation.domain.parameterization.orchestrator import (
    build_params,
)
from src.agents.fundamental.core_valuation.domain.valuation_model_registry import (
    ValuationModelRegistry,
)
from src.agents.fundamental.financial_statements.interface.contracts import (
    parse_financial_reports_model,
)
from src.agents.fundamental.financial_statements.interface.parsers import (
    parse_financial_health_payload,
)
from src.agents.fundamental.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.forward_signals.interface.serializers import (
    serialize_forward_signals,
)
from src.agents.fundamental.model_selection.domain.model_selection import (
    select_valuation_model,
)
from src.agents.fundamental.workflow_orchestrator.application.dto import (
    FundamentalAppContextDTO,
)
from src.agents.fundamental.workflow_orchestrator.application.orchestrator import (
    FundamentalNodeResult,
    FundamentalOrchestrator,
)
from src.agents.fundamental.workflow_orchestrator.application.ports import (
    FundamentalFinancialPayload,
    IFundamentalFinancialPayloadProvider,
    IFundamentalMarketDataService,
    IFundamentalReportRepo,
)
from src.agents.fundamental.workflow_orchestrator.application.services.valuation_replay_contracts import (
    INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY,
)
from src.agents.fundamental.workflow_orchestrator.interface.contracts import (
    FundamentalPreviewInputModel,
)
from src.agents.fundamental.workflow_orchestrator.interface.mappers import (
    summarize_fundamental_for_preview,
)
from src.agents.fundamental.workflow_orchestrator.interface.serializers import (
    build_model_selection_artifact,
    build_model_selection_report_payload,
    build_valuation_artifact,
    normalize_model_selection_reports,
)
from src.interface.events.schemas import build_artifact_payload
from src.shared.kernel.contracts import OUTPUT_KIND_FUNDAMENTAL_ANALYSIS


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
    fetch_financial_payload_fn: IFundamentalFinancialPayloadProvider
    market_data_service: IFundamentalMarketDataService
    financial_payload_years: int = 5

    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        def _fetch_and_parse_financial_health_payload(
            ticker: str,
        ):
            payload: FundamentalFinancialPayload = self.fetch_financial_payload_fn(
                ticker, years=self.financial_payload_years
            )
            return parse_financial_health_payload(
                payload,
                context="financial_health.payload",
            )

        return await self.orchestrator.run_financial_health(
            state,
            fetch_financial_data_fn=_fetch_and_parse_financial_health_payload,
        )

    async def run_model_selection(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_model_selection(
            state,
            select_valuation_model_fn=select_valuation_model,
        )

    async def run_valuation(self, state: Mapping[str, object]) -> FundamentalNodeResult:
        def _build_params_with_market_data(
            model_type: str,
            ticker: str | None,
            reports_raw: list[dict[str, object]],
            forward_signals: list[ForwardSignalPayload] | None,
        ) -> ParamBuildResult:
            canonical_reports = parse_financial_reports_model(
                reports_raw,
                context="valuation.financial_reports",
                inject_default_provenance=True,
            )
            market_snapshot: dict[str, object] | None = None
            if ticker:
                market_snapshot = self.market_data_service.get_market_snapshot(
                    ticker
                ).to_mapping()
            if market_snapshot is None and forward_signals:
                market_snapshot = {}
            if isinstance(market_snapshot, dict) and forward_signals:
                serialized_signals = serialize_forward_signals(forward_signals)
                if serialized_signals is not None:
                    market_snapshot["forward_signals"] = serialized_signals
            build_result = build_params(
                model_type,
                ticker,
                canonical_reports,
                market_snapshot=market_snapshot,
            )
            if not isinstance(market_snapshot, dict):
                return build_result

            replay_metadata: dict[str, object] = {}
            if isinstance(build_result.metadata, Mapping):
                replay_metadata.update(dict(build_result.metadata))
            replay_metadata[INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY] = dict(market_snapshot)
            return ParamBuildResult(
                params=build_result.params,
                trace_inputs=build_result.trace_inputs,
                missing=build_result.missing,
                assumptions=build_result.assumptions,
                metadata=replay_metadata,
            )

        return await self.orchestrator.run_valuation(
            state,
            build_params_fn=_build_params_with_market_data,
            get_model_runtime_fn=ValuationModelRegistry.get_model_runtime,
        )


def build_fundamental_workflow_runner(
    *,
    orchestrator: FundamentalOrchestrator,
    fetch_financial_payload_fn: IFundamentalFinancialPayloadProvider,
    market_data_service: IFundamentalMarketDataService,
    financial_payload_years: int = 5,
) -> FundamentalWorkflowRunner:
    return FundamentalWorkflowRunner(
        orchestrator=orchestrator,
        fetch_financial_payload_fn=fetch_financial_payload_fn,
        market_data_service=market_data_service,
        financial_payload_years=financial_payload_years,
    )
