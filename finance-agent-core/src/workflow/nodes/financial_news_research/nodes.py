from langgraph.graph import END
from langgraph.types import Command

from src.agents.news.application.factory import news_workflow_runner

from .subgraph_state import FinancialNewsState


def _resolve_goto(goto: str) -> str:
    return END if goto == "END" else goto


async def search_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    result = await news_workflow_runner.run_search(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    result = await news_workflow_runner.run_selector(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    result = await news_workflow_runner.run_fetch(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    result = await news_workflow_runner.run_analyst(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    result = await news_workflow_runner.run_aggregator(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))
