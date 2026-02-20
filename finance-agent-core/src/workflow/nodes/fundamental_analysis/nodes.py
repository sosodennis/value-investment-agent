from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.application.factory import fundamental_workflow_runner
from src.workflow.command_adapter import command_from_result

from .subgraph_state import FundamentalAnalysisState


async def financial_health_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_financial_health(state)
    return command_from_result(result, end_node=END)


async def model_selection_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_model_selection(state)
    return command_from_result(result, end_node=END)


async def valuation_node(state: FundamentalAnalysisState) -> Command:
    result = await fundamental_workflow_runner.run_valuation(state)
    return command_from_result(result, end_node=END)
