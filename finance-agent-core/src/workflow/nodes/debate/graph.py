from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ...state import AgentState
from .nodes import (
    bear_node,
    bull_node,
    debate_aggregator_node,
    moderator_node,
)


async def get_debate_subgraph():
    """
    Build and return the cognitive debate sub-graph with blind debate mechanism.

    Round 1: Bull and Bear execute in PARALLEL (blind debate - no anchoring)
             Using LangGraph's Send API for dynamic fan-out.
    Round 2+: Sequential execution with cross-review (each sees the other's arguments)
    """
    builder = StateGraph(AgentState)

    # 1. Add Nodes
    builder.add_node("debate_aggregator", debate_aggregator_node)
    builder.add_node("bull", bull_node)
    builder.add_node("bear", bear_node)
    builder.add_node("moderator", moderator_node)

    # 2. Define Edges
    builder.add_edge(START, "debate_aggregator")

    # Conditional routing from aggregator: Parallel in Round 1, Sequential in Round 2+
    def route_from_aggregator(state: AgentState):
        """
        Round 1: Fan out to both Bull and Bear in parallel using Send API.
        Round 2+: Sequential flow (Bull first).
        """
        if state.debate_current_round == 0:
            # Round 1: Parallel execution - both see only analyst_reports, not each other
            return [
                Send("bull", state),
                Send("bear", state),
            ]
        else:
            # Round 2+: Sequential - Bull goes first, then Bear
            return "bull"

    builder.add_conditional_edges(
        "debate_aggregator",
        route_from_aggregator,
        ["bull", "bear"],  # Possible destinations
    )

    # Routing from Bull: In Round 1 (parallel), go directly to moderator
    # In Round 2+, go to Bear first (sequential)
    def route_from_bull(state: AgentState):
        """After Bull speaks, route based on round."""
        if state.debate_current_round == 0:
            # Round 1: Parallel mode - Bull's output goes to moderator directly
            # (Bear also goes there independently)
            return "moderator"
        else:
            # Round 2+: Sequential - Bull -> Bear -> Moderator
            return "bear"

    builder.add_conditional_edges("bull", route_from_bull, ["bear", "moderator"])

    # Bear always goes to moderator (either from parallel R1 or sequential R2+)
    builder.add_edge("bear", "moderator")

    # 3. Moderator Loop: Continue debate or end
    def should_continue_debate(state: AgentState):
        """
        Decision node to either continue the debate or finish.
        After R1 moderator critique, goes back to aggregator to route properly.
        """
        if state.debate_current_round >= 3:
            return END

        # Continue: Go back to aggregator for proper routing
        return "debate_aggregator"

    builder.add_conditional_edges(
        "moderator", should_continue_debate, ["debate_aggregator", END]
    )

    return builder.compile()
