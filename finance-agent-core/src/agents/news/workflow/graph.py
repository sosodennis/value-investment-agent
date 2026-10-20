from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.news.application.factory import NewsWorkflowRunner

from .nodes import build_news_nodes
from .state import FinancialNewsInput, FinancialNewsOutput, FinancialNewsState


def build_news_workflow(runner: NewsWorkflowRunner) -> CompiledStateGraph:
    nodes = build_news_nodes(runner)
    builder = StateGraph(
        FinancialNewsState,
        input_schema=FinancialNewsInput,
        output_schema=FinancialNewsOutput,
    )
    builder.add_node(
        "search_node",
        nodes["search_node"],
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "selector_node",
        nodes["selector_node"],
        metadata={"agent_id": "financial_news_research"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "fetch_node",
        nodes["fetch_node"],
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "analyst_node",
        nodes["analyst_node"],
        metadata={"agent_id": "financial_news_research"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "aggregator_node",
        nodes["aggregator_node"],
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_edge(START, "search_node")
    return builder.compile()
