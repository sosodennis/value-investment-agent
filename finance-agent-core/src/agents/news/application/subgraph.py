"""
Financial News Research subgraph entrypoint owned by the news agent package.
"""

from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from src.workflow.nodes.financial_news_research.nodes import (
    aggregator_node,
    analyst_node,
    fetch_node,
    search_node,
    selector_node,
)
from src.workflow.nodes.financial_news_research.subgraph_state import (
    FinancialNewsInput,
    FinancialNewsOutput,
    FinancialNewsState,
)


def build_financial_news_subgraph():
    """Build and return the financial_news_research subgraph."""
    builder = StateGraph(
        FinancialNewsState,
        input_schema=FinancialNewsInput,
        output_schema=FinancialNewsOutput,
    )
    builder.add_node(
        "search_node",
        search_node,
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "selector_node",
        selector_node,
        metadata={"agent_id": "financial_news_research"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "fetch_node",
        fetch_node,
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "analyst_node",
        analyst_node,
        metadata={"agent_id": "financial_news_research"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "aggregator_node",
        aggregator_node,
        metadata={"agent_id": "financial_news_research"},
    )

    builder.add_edge(START, "search_node")
    return builder.compile()
