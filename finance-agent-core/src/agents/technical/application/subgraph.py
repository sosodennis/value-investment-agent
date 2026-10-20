from langgraph.graph.state import CompiledStateGraph

from src.agents.technical.application.wiring import get_technical_workflow_runner
from src.agents.technical.entrypoint import build_technical_subgraph as build_graph


def build_technical_subgraph() -> CompiledStateGraph:
    return build_graph(get_technical_workflow_runner())


__all__ = ["build_technical_subgraph"]
