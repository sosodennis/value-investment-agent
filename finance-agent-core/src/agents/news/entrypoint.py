from langgraph.graph.state import CompiledStateGraph

from src.agents.news.application.factory import NewsWorkflowRunner
from src.agents.news.workflow.graph import build_news_workflow
from src.agents.news.workflow.state import (
    FinancialNewsInput,
    FinancialNewsOutput,
)


def build_financial_news_subgraph(
    runner: NewsWorkflowRunner | None = None,
) -> CompiledStateGraph:
    if runner is None:
        from src.agents.news.application.wiring import get_news_workflow_runner

        runner = get_news_workflow_runner()
    return build_news_workflow(runner)


__all__ = [
    "FinancialNewsInput",
    "FinancialNewsOutput",
    "build_financial_news_subgraph",
]
