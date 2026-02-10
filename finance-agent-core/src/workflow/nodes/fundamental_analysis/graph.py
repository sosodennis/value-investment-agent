"""
Fundamental Analysis Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
Uses Command and interrupt for control flow.
"""

from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from .nodes import financial_health_node, model_selection_node, valuation_node
from .subgraph_state import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
)

# --- Graph Construction ---


def build_fundamental_subgraph():
    """纯函數：構建並編譯子圖"""
    builder = StateGraph(
        FundamentalAnalysisState,
        input=FundamentalAnalysisInput,
        output=FundamentalAnalysisOutput,
    )
    builder.add_node(
        "financial_health",
        financial_health_node,
        metadata={"agent_id": "fundamental_analysis"},
        retry=RetryPolicy(
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

    # 注意：這裡不需要傳入 checkpointer，因為它會繼承父圖的
    return builder.compile()
