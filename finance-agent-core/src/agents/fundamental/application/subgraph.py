"""
Fundamental Analysis subgraph entrypoint owned by the fundamental agent package.
"""

from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from src.workflow.nodes.fundamental_analysis.nodes import (
    financial_health_node,
    model_selection_node,
    valuation_node,
)
from src.workflow.nodes.fundamental_analysis.subgraph_state import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
)


def build_fundamental_subgraph():
    """Build and return the fundamental_analysis subgraph."""
    builder = StateGraph(
        FundamentalAnalysisState,
        input_schema=FundamentalAnalysisInput,
        output_schema=FundamentalAnalysisOutput,
    )
    builder.add_node(
        "financial_health",
        financial_health_node,
        metadata={"agent_id": "fundamental_analysis"},
        retry_policy=RetryPolicy(
            max_attempts=3,
            backoff_factor=2.0,
            initial_interval=0.5,
            jitter=True,
        ),
    )
    builder.add_node(
        "model_selection",
        model_selection_node,
        metadata={"agent_id": "fundamental_analysis"},
    )
    builder.add_node(
        "calculation",
        valuation_node,
        metadata={"agent_id": "fundamental_analysis"},
    )
    builder.add_edge(START, "financial_health")
    builder.add_edge("financial_health", "model_selection")
    builder.add_edge("model_selection", "calculation")
    return builder.compile()
