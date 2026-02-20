from langgraph.graph import END
from langgraph.types import Command

from src.agents.news.application.factory import news_workflow_runner
from src.workflow.command_adapter import command_from_result

from .subgraph_state import FinancialNewsState


async def search_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    result = await news_workflow_runner.run_search(state)
    return command_from_result(result, end_node=END)


async def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    result = await news_workflow_runner.run_selector(state)
    return command_from_result(result, end_node=END)


async def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    result = await news_workflow_runner.run_fetch(state)
    return command_from_result(result, end_node=END)


async def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    result = await news_workflow_runner.run_analyst(state)
    return command_from_result(result, end_node=END)


async def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    result = await news_workflow_runner.run_aggregator(state)
    return command_from_result(result, end_node=END)
