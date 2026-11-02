from __future__ import annotations

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.technical.workflow.nodes import (
    TechnicalWorkflowRunnerPort,
    build_technical_nodes,
)
from src.agents.technical.workflow.state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
    TechnicalAnalysisState,
)

_ACTIVITY_METADATA = {
    "data_fetch": (("technical_analysis", "fetch-market-data"), "Fetch market data"),
    "feature_compute": (
        ("technical_analysis", "compute-features"),
        "Compute indicators",
    ),
    "pattern_compute": (("technical_analysis", "detect-patterns"), "Detect patterns"),
    "alerts_compute": (("technical_analysis", "evaluate-alerts"), "Evaluate alerts"),
    "regime_compute": (
        ("technical_analysis", "classify-regime"),
        "Classify market regime",
    ),
    "fusion_compute": (("technical_analysis", "fuse-signals"), "Fuse signals"),
    "verification_compute": (
        ("technical_analysis", "verify-signals"),
        "Verify signals",
    ),
    "semantic_translate": (
        ("technical_analysis", "summarize-signals"),
        "Summarize signals",
    ),
}


def build_technical_workflow(
    runner: TechnicalWorkflowRunnerPort,
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
        scope_path, activity_label = _ACTIVITY_METADATA[name]
        builder.add_node(
            name,
            RunnableLambda(nodes[name]).with_config(tags=["hide_stream"]),
            metadata={
                "agent_id": "technical_analysis",
                "workflow_activity_kind": "node",
                "workflow_scope_path": scope_path,
                "activity_label": activity_label,
            },
        )
    builder.add_node(
        "semantic_translate",
        nodes["semantic_translate"],
        metadata={
            "agent_id": "technical_analysis",
            "workflow_activity_kind": "node",
            "workflow_scope_path": _ACTIVITY_METADATA["semantic_translate"][0],
            "activity_label": _ACTIVITY_METADATA["semantic_translate"][1],
        },
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
