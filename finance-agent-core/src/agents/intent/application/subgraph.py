"""
Intent Extraction subgraph entrypoint owned by the intent agent package.
"""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph

from src.workflow.nodes.intent_extraction.nodes import (
    clarification_node,
    decision_node,
    extraction_node,
    searching_node,
)
from src.workflow.nodes.intent_extraction.subgraph_state import (
    IntentExtractionInput,
    IntentExtractionOutput,
    IntentExtractionState,
)


def build_intent_extraction_subgraph():
    """Build and return the intent_extraction subgraph."""
    builder = StateGraph(
        IntentExtractionState,
        input_schema=IntentExtractionInput,
        output_schema=IntentExtractionOutput,
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
    return builder.compile()
