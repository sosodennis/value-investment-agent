from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from src.agents.intent.application import factory
from src.agents.intent.application.ports import IntentRuntimePorts
from src.agents.intent.interface.interrupts import HumanTickerSelection, InterruptValue
from src.agents.intent.workflow.subgraph import build_intent_workflow


def build_intent_extraction_graph(
    runtime_ports: IntentRuntimePorts | None = None,
) -> CompiledStateGraph:
    """Build the public intent extraction graph from its runtime adapters."""
    if runtime_ports is None:
        from src.agents.intent.application.wiring import get_intent_orchestrator

        orchestrator = get_intent_orchestrator()
    else:
        orchestrator = factory.build_intent_orchestrator(runtime_ports=runtime_ports)
    return build_intent_workflow(orchestrator)


__all__ = ["HumanTickerSelection", "InterruptValue", "build_intent_extraction_graph"]
