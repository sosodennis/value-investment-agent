from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from src.agents.fundamental.workflow.graph import build_fundamental_workflow
from src.agents.fundamental.workflow.nodes import FundamentalWorkflowRunner
from src.agents.fundamental.workflow.state import (
    FundamentalAnalysisContext,
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
    IntentExtractionContext,
)


def build_fundamental_subgraph(
    runner: FundamentalWorkflowRunner | None = None,
) -> CompiledStateGraph:
    if runner is None:
        from src.agents.fundamental.application.wiring import (
            get_fundamental_workflow_runner,
        )

        runner = get_fundamental_workflow_runner()
    return build_fundamental_workflow(runner)


__all__ = [
    "FundamentalAnalysisContext",
    "FundamentalAnalysisInput",
    "FundamentalAnalysisOutput",
    "FundamentalAnalysisState",
    "IntentExtractionContext",
    "build_fundamental_subgraph",
]
