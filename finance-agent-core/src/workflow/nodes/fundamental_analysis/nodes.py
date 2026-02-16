from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.orchestrator import FundamentalOrchestrator
from src.agents.fundamental.data.clients.sec_xbrl.utils import fetch_financial_data
from src.agents.fundamental.data.ports import fundamental_artifact_port
from src.agents.fundamental.domain.model_selection import select_valuation_model
from src.agents.fundamental.domain.valuation.param_builder import build_params
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
from src.shared.kernel.tools.logger import get_logger

from .subgraph_state import FundamentalAnalysisState

logger = get_logger(__name__)


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


fundamental_orchestrator = FundamentalOrchestrator(
    port=fundamental_artifact_port,
    summarize_preview=_summarize_preview,
    build_progress_artifact=_build_progress_artifact,
    normalize_model_selection_reports=normalize_model_selection_reports,
    build_model_selection_report_payload=build_model_selection_report_payload,
    build_model_selection_artifact=build_model_selection_artifact,
    build_valuation_artifact=build_valuation_artifact,
)


async def financial_health_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_orchestrator.run_financial_health(
        state,
        fetch_financial_data_fn=lambda ticker: fetch_financial_data(ticker, years=3),
        normalize_financial_reports_fn=parse_financial_reports_model,
    )
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )


async def model_selection_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_orchestrator.run_model_selection(
        state,
        select_valuation_model_fn=select_valuation_model,
    )
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )


async def valuation_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_orchestrator.run_valuation(
        state,
        build_params_fn=build_params,
        get_skill_fn=SkillRegistry.get_skill,
    )
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )
