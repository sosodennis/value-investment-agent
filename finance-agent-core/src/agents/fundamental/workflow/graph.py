from __future__ import annotations

from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.fundamental.workflow.nodes import (
    FundamentalWorkflowRunner,
    build_fundamental_nodes,
)
from src.agents.fundamental.workflow.state import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
)


def build_fundamental_workflow(
    runner: FundamentalWorkflowRunner,
) -> CompiledStateGraph:
    nodes = build_fundamental_nodes(runner)
    builder = StateGraph(
        FundamentalAnalysisState,
        input_schema=FundamentalAnalysisInput,
        output_schema=FundamentalAnalysisOutput,
    )
    builder.add_node(
        "financial_health",
        nodes["financial_health"],
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
        nodes["model_selection"],
        metadata={"agent_id": "fundamental_analysis"},
    )
    builder.add_node(
        "calculation",
        nodes["calculation"],
        metadata={"agent_id": "fundamental_analysis"},
    )
    builder.add_edge(START, "financial_health")
    builder.add_edge("financial_health", "model_selection")
    builder.add_edge("model_selection", "calculation")
    return builder.compile()


__all__ = ["build_fundamental_workflow"]
