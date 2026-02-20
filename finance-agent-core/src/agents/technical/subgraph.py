"""
Technical Analysis subgraph entrypoint owned by the technical agent package.
"""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from src.workflow.nodes.technical_analysis.nodes import (
    data_fetch_node,
    fracdiff_compute_node,
    semantic_translate_node,
)
from src.workflow.nodes.technical_analysis.subgraph_state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
    TechnicalAnalysisState,
)


def build_technical_subgraph():
    """Build and return the technical_analysis subgraph."""
    builder = StateGraph(
        TechnicalAnalysisState,
        input_schema=TechnicalAnalysisInput,
        output_schema=TechnicalAnalysisOutput,
    )
    builder.add_node(
        "data_fetch",
        RunnableLambda(data_fetch_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "fracdiff_compute",
        RunnableLambda(fracdiff_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "semantic_translate",
        semantic_translate_node,
        metadata={"agent_id": "technical_analysis"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_edge(START, "data_fetch")
    builder.add_edge("data_fetch", "fracdiff_compute")
    builder.add_edge("fracdiff_compute", "semantic_translate")
    return builder.compile()
