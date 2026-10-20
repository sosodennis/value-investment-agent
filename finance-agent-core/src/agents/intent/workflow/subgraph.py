from __future__ import annotations

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.intent.application.orchestrator import IntentOrchestrator

from .nodes import build_intent_nodes
from .state import IntentExtractionInput, IntentExtractionOutput, IntentExtractionState


def build_intent_workflow(
    orchestrator: IntentOrchestrator,
) -> CompiledStateGraph:
    builder = StateGraph(
        IntentExtractionState,
        input_schema=IntentExtractionInput,
        output_schema=IntentExtractionOutput,
    )
    for name, node in build_intent_nodes(orchestrator).items():
        builder.add_node(
            name,
            RunnableLambda(node).with_config(tags=["hide_stream"]),
            metadata={"agent_id": "intent_extraction"},
        )
    builder.add_edge(START, "extraction")
    return builder.compile()
