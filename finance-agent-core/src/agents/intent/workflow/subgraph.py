from __future__ import annotations

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.intent.application.orchestrator import IntentOrchestrator

from .nodes import build_intent_nodes
from .state import IntentExtractionInput, IntentExtractionOutput, IntentExtractionState

_ACTIVITY_METADATA = {
    "extraction": (("intent_extraction", "extract-request"), "Extract request"),
    "searching": (("intent_extraction", "find-company"), "Find company"),
    "deciding": (("intent_extraction", "resolve-company"), "Resolve company"),
    "clarifying": (("intent_extraction", "confirm-company"), "Confirm company"),
}


def build_intent_workflow(
    orchestrator: IntentOrchestrator,
) -> CompiledStateGraph:
    builder = StateGraph(
        IntentExtractionState,
        input_schema=IntentExtractionInput,
        output_schema=IntentExtractionOutput,
    )
    for name, node in build_intent_nodes(orchestrator).items():
        scope_path, activity_label = _ACTIVITY_METADATA[name]
        builder.add_node(
            name,
            RunnableLambda(node).with_config(tags=["hide_stream"]),
            metadata={
                "agent_id": "intent_extraction",
                "workflow_activity_kind": "node",
                "workflow_scope_path": scope_path,
                "activity_label": activity_label,
            },
        )
    builder.add_edge(START, "extraction")
    return builder.compile()
