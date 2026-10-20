"""Compatibility builder for root composition pending its entrypoint migration."""

from langgraph.graph.state import CompiledStateGraph

from src.agents.intent.application.wiring import get_intent_orchestrator
from src.agents.intent.workflow.subgraph import build_intent_workflow


def build_intent_extraction_subgraph() -> CompiledStateGraph:
    """Build the agent-owned intent workflow for the legacy root caller."""
    return build_intent_workflow(get_intent_orchestrator())
