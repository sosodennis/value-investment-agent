from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END
from langgraph.types import Command

from src.agents.news.application.factory import NewsWorkflowRunner
from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.shared.kernel.workflow_routing import resolve_end_goto

from .state import FinancialNewsState

Node = Callable[[FinancialNewsState], Awaitable[Command]]


def _adapt(
    call: Callable[[FinancialNewsState], Awaitable[WorkflowNodeResult]],
) -> Node:
    async def node(state: FinancialNewsState) -> Command:
        result = await call(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto(result.goto, end_node=END),
        )

    return node


def build_news_nodes(runner: NewsWorkflowRunner) -> dict[str, Node]:
    return {
        "search_node": _adapt(runner.run_search),
        "selector_node": _adapt(runner.run_selector),
        "fetch_node": _adapt(runner.run_fetch),
        "analyst_node": _adapt(runner.run_analyst),
        "aggregator_node": _adapt(runner.run_aggregator),
    }
