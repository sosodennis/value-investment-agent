from __future__ import annotations

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.technical.application.factory import TechnicalWorkflowRunner
from src.agents.technical.workflow.nodes import build_technical_nodes
from src.agents.technical.workflow.state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
    TechnicalAnalysisState,
)


def build_technical_workflow(
    runner: TechnicalWorkflowRunner,
) -> CompiledStateGraph:
    nodes = build_technical_nodes(runner)
    builder = StateGraph(
        TechnicalAnalysisState,
        input_schema=TechnicalAnalysisInput,
        output_schema=TechnicalAnalysisOutput,
    )
    for name in (
        "data_fetch",
        "feature_compute",
        "pattern_compute",
        "alerts_compute",
        "regime_compute",
        "fusion_compute",
        "verification_compute",
    ):
        builder.add_node(
            name,
            RunnableLambda(nodes[name]).with_config(tags=["hide_stream"]),
            metadata={"agent_id": "technical_analysis"},
        )
    builder.add_node(
        "semantic_translate",
        nodes["semantic_translate"],
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
