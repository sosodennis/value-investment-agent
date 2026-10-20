from langgraph.graph.state import CompiledStateGraph

from src.agents.technical.workflow.graph import build_technical_workflow
from src.agents.technical.workflow.nodes import TechnicalWorkflowRunnerPort
from src.agents.technical.workflow.state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
)


def build_technical_subgraph(
    runner: TechnicalWorkflowRunnerPort | None = None,
) -> CompiledStateGraph:
    if runner is None:
        from src.agents.technical.application.wiring import (
            get_technical_workflow_runner,
        )

        runner = get_technical_workflow_runner()
    return build_technical_workflow(runner)


__all__ = [
    "TechnicalAnalysisInput",
    "TechnicalAnalysisOutput",
    "build_technical_subgraph",
]
