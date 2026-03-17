"""
Technical Analysis subgraph entrypoint owned by the technical agent package.
"""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.types import RetryPolicy

from src.workflow.nodes.technical_analysis.nodes import (
    alerts_compute_node,
    data_fetch_node,
    feature_compute_node,
    fusion_compute_node,
    pattern_compute_node,
    regime_compute_node,
    semantic_translate_node,
    verification_compute_node,
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
        "feature_compute",
        RunnableLambda(feature_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "pattern_compute",
        RunnableLambda(pattern_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "alerts_compute",
        RunnableLambda(alerts_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "regime_compute",
        RunnableLambda(regime_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "fusion_compute",
        RunnableLambda(fusion_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "verification_compute",
        RunnableLambda(verification_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "semantic_translate",
        semantic_translate_node,
        metadata={"agent_id": "technical_analysis"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_edge(START, "data_fetch")
    builder.add_edge("data_fetch", "feature_compute")
    builder.add_edge("feature_compute", "pattern_compute")
    builder.add_edge("pattern_compute", "alerts_compute")
    builder.add_edge("alerts_compute", "regime_compute")
    builder.add_edge("regime_compute", "fusion_compute")
    builder.add_edge("fusion_compute", "verification_compute")
    builder.add_edge("verification_compute", "semantic_translate")
    return builder.compile()
