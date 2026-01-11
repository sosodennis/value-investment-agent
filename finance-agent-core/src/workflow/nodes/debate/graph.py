from langgraph.graph import END, START, StateGraph

from ...state import AgentState
from .nodes import (
    bear_node,
    bull_node,
    debate_aggregator_node,
    moderator_node,
)


async def get_debate_subgraph():
    """
    Build and return the cognitive debate sub-graph.
    This graph follows a cyclic pattern: Aggregator -> Bull -> Bear -> Moderator -> [Loop back to Bull] -> END
    """
    builder = StateGraph(AgentState)

    # 1. Add Nodes
    builder.add_node("debate_aggregator", debate_aggregator_node)
    builder.add_node("bull", bull_node)
    builder.add_node("bear", bear_node)
    builder.add_node("moderator", moderator_node)

    # 2. Define Edges (Standard Flow)
    builder.add_edge(START, "debate_aggregator")
    builder.add_edge("debate_aggregator", "bull")
    builder.add_edge("bull", "bear")
    builder.add_edge("bear", "moderator")

    # 3. Add Conditional Routing (The Circular Loop)
    def should_continue_debate(state: AgentState):
        """
        Decision node to either continue the debate or finish.
        """
        # Limit to MAX_ROUNDS (e.g., 3)
        # Note: current_round is incremented in the moderator_node
        if state.debate_current_round >= 3:
            return END

        # Future: Add logic to detect consensus or stalemate
        return "bull"

    builder.add_conditional_edges(
        "moderator", should_continue_debate, {"bull": "bull", END: END}
    )

    return builder.compile()
