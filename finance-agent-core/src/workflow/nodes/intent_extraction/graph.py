"""
Intent Extraction Subgraph.
"""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph

from .nodes import clarification_node, decision_node, extraction_node, searching_node
from .subgraph_state import (
    IntentExtractionInput,
    IntentExtractionOutput,
    IntentExtractionState,
)


def build_intent_extraction_subgraph():
    """Build and return the intent_extraction subgraph."""
    # 1. Build Subgraph
    builder = StateGraph(
        IntentExtractionState,
        input=IntentExtractionInput,
        output=IntentExtractionOutput,
    )
    builder.add_node(
        "extraction",
        RunnableLambda(extraction_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "intent_extraction"},
    )
    builder.add_node(
        "searching",
        RunnableLambda(searching_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "intent_extraction"},
    )
    builder.add_node(
        "deciding",
        RunnableLambda(decision_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "intent_extraction"},
    )
    builder.add_node(
        "clarifying",
        RunnableLambda(clarification_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "intent_extraction"},
    )
    builder.add_edge(START, "extraction")

    # 2. Compile
    # Note: No checkpointer passed here; it will be inherited from the parent graph
    return builder.compile()
