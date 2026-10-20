"""Compatibility node delegates; ownership lives in the news agent workflow."""

from langgraph.types import Command

from src.agents.news.application.wiring import get_news_workflow_runner
from src.agents.news.workflow.nodes import build_news_nodes
from src.agents.news.workflow.state import FinancialNewsState


async def _run(node_name: str, state: FinancialNewsState) -> Command:
    return await build_news_nodes(get_news_workflow_runner())[node_name](state)


async def search_node(state: FinancialNewsState) -> Command:
    return await _run("search_node", state)


async def selector_node(state: FinancialNewsState) -> Command:
    return await _run("selector_node", state)


async def fetch_node(state: FinancialNewsState) -> Command:
    return await _run("fetch_node", state)


async def analyst_node(state: FinancialNewsState) -> Command:
    return await _run("analyst_node", state)


async def aggregator_node(state: FinancialNewsState) -> Command:
    return await _run("aggregator_node", state)
