from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.orchestrator import (
    FundamentalNodeResult,
    FundamentalOrchestrator,
)
from src.agents.fundamental.data.clients.market_data import market_data_client
from src.agents.fundamental.data.clients.sec_xbrl.utils import fetch_financial_data
from src.agents.fundamental.data.ports import fundamental_artifact_port
from src.agents.fundamental.domain.model_selection import select_valuation_model
from src.agents.fundamental.domain.valuation.param_builder import (
    ParamBuildResult,
    build_params,
)
from src.agents.fundamental.domain.valuation.registry import SkillRegistry
from src.agents.fundamental.interface.contracts import (
    FundamentalPreviewInputModel,
    parse_financial_reports_model,
)
from src.agents.fundamental.interface.mappers import summarize_fundamental_for_preview
from src.agents.fundamental.interface.serializers import (
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


def build_fundamental_orchestrator() -> FundamentalOrchestrator:
    return FundamentalOrchestrator(
        port=fundamental_artifact_port,
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

    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_financial_health(
            state,
            fetch_financial_data_fn=lambda ticker: fetch_financial_data(
                ticker, years=3
            ),
            normalize_financial_reports_fn=parse_financial_reports_model,
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
        ) -> ParamBuildResult:
            market_snapshot: dict[str, object] | None = None
            if ticker:
                market_snapshot = market_data_client.get_market_snapshot(
                    ticker
                ).to_mapping()
            return build_params(
                model_type,
                ticker,
                reports_raw,
                market_snapshot=market_snapshot,
            )

        return await self.orchestrator.run_valuation(
            state,
            build_params_fn=_build_params_with_market_data,
            get_skill_fn=SkillRegistry.get_skill,
        )


def build_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    return FundamentalWorkflowRunner(orchestrator=build_fundamental_orchestrator())


fundamental_workflow_runner = build_fundamental_workflow_runner()
