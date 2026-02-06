from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from .nodes import (
    aggregator_node,
    analyst_node,
    fetch_node,
    search_node,
    selector_node,
)
from .subgraph_state import (
    FinancialNewsInput,
    FinancialNewsOutput,
    FinancialNewsState,
)


def build_financial_news_subgraph():
    """Build and return the financial_news_research subgraph."""
    builder = StateGraph(
        FinancialNewsState, input=FinancialNewsInput, output=FinancialNewsOutput
    )
    builder.add_node(
        "search_node", search_node, metadata={"agent_id": "financial_news_research"}
    )
    builder.add_node(
        "selector_node",
        selector_node,
        metadata={"agent_id": "financial_news_research"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "fetch_node", fetch_node, metadata={"agent_id": "financial_news_research"}
    )
    builder.add_node(
        "analyst_node",
        analyst_node,
        metadata={"agent_id": "financial_news_research"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "aggregator_node",
        aggregator_node,
        metadata={"agent_id": "financial_news_research"},
    )

    builder.add_edge(START, "search_node")
    # Transitions are handled by Command(goto=...) in the nodes.

    return builder.compile()
