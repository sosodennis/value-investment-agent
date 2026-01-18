"""
Intent Extraction Subgraph.
"""

from langgraph.graph import START, StateGraph

from ...state import AgentState
from .nodes import clarification_node, decision_node, extraction_node, searching_node

# Helper for initialization
intent_extraction_subgraph = None


async def get_intent_extraction_subgraph():
    """Lazy-initialize and return the intent_extraction subgraph."""
    global intent_extraction_subgraph
    if intent_extraction_subgraph is None:
        # 1. Build Subgraph
        builder = StateGraph(AgentState)
        builder.add_node("extraction", extraction_node)
        builder.add_node("searching", searching_node)
        builder.add_node("deciding", decision_node)
        builder.add_node("clarifying", clarification_node)
        builder.add_edge(START, "extraction")

        # 2. Compile
        # Note: No checkpointer passed here; it will be inherited from the parent graph
        intent_extraction_subgraph = builder.compile()

    return intent_extraction_subgraph
