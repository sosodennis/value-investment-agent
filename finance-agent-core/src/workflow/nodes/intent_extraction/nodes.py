"""Compatibility exports for the agent-owned intent workflow nodes."""

from collections.abc import Callable

from langgraph.types import Command

from src.agents.intent.application.wiring import get_intent_orchestrator
from src.agents.intent.workflow.nodes import build_intent_nodes
from src.agents.intent.workflow.state import IntentExtractionState

intent_orchestrator = get_intent_orchestrator()
_intent_nodes = build_intent_nodes(intent_orchestrator)

extraction_node: Callable[[IntentExtractionState], Command] = _intent_nodes[
    "extraction"
]
searching_node: Callable[[IntentExtractionState], Command] = _intent_nodes["searching"]
decision_node: Callable[[IntentExtractionState], Command] = _intent_nodes["deciding"]
clarification_node: Callable[[IntentExtractionState], Command] = _intent_nodes[
    "clarifying"
]
