from __future__ import annotations

from src.agents.intent.application.orchestrator import IntentOrchestrator
from src.agents.intent.application.ports import IntentRuntimePorts


def build_intent_orchestrator(
    *,
    runtime_ports: IntentRuntimePorts,
) -> IntentOrchestrator:
    return IntentOrchestrator(runtime_ports=runtime_ports)
