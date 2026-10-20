from langgraph.graph.state import CompiledStateGraph

from src.agents.technical.application.factory import TechnicalWorkflowRunner
from src.agents.technical.workflow.graph import build_technical_workflow
from src.agents.technical.workflow.state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
)


def build_technical_subgraph(
    runner: TechnicalWorkflowRunner,
) -> CompiledStateGraph:
    return build_technical_workflow(runner)


__all__ = [
    "TechnicalAnalysisInput",
    "TechnicalAnalysisOutput",
    "build_technical_subgraph",
]
