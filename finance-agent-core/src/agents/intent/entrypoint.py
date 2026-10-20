from __future__ import annotations

from src.agents.intent.application import factory
from src.agents.intent.application.ports import IntentRuntimePorts
from src.agents.intent.workflow.subgraph import build_intent_workflow


def build_intent_extraction_graph(runtime_ports: IntentRuntimePorts):
    """Build the public intent extraction graph from its runtime adapters."""
    orchestrator = factory.build_intent_orchestrator(runtime_ports=runtime_ports)
    return build_intent_workflow(orchestrator)
