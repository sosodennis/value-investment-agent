from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.application.orchestrator import fundamental_orchestrator
from src.agents.fundamental.data.clients.sec_xbrl.utils import fetch_financial_data
from src.agents.fundamental.domain.model_selection import select_valuation_model
from src.agents.fundamental.domain.valuation.param_builder import build_params
from src.agents.fundamental.domain.valuation.registry import SkillRegistry
from src.common.tools.logger import get_logger
from src.interface.canonical_serializers import (
    normalize_financial_reports,
)

from .subgraph_state import FundamentalAnalysisState

logger = get_logger(__name__)


async def financial_health_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_orchestrator.run_financial_health(
        state,
        fetch_financial_data_fn=lambda ticker: fetch_financial_data(ticker, years=3),
        normalize_financial_reports_fn=normalize_financial_reports,
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
