from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.application.factory import fundamental_workflow_runner

from .subgraph_state import FundamentalAnalysisState


async def financial_health_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_financial_health(state)
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )


async def model_selection_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_model_selection(state)
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )


async def valuation_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_valuation(state)
    return Command(
        update=result.update, goto=END if result.goto == "END" else result.goto
    )
