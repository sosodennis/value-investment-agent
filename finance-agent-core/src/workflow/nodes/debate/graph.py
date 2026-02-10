from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from .nodes import (
    debate_aggregator_node,
    fact_extractor_node,
    r1_bear_node,
    r1_bull_node,
    r1_moderator_node,
    r2_bear_node,
    r2_bull_node,
    r2_moderator_node,
    r3_bear_node,
    r3_bull_node,
    verdict_node,
)
from .subgraph_state import DebateInput, DebateOutput, DebateState


def build_debate_subgraph():
    """
    Build and return the cognitive debate sub-graph with blind debate mechanism.

    Uses isolated DebateState (not AgentState) to prevent stale status updates.

    Round 1 (Parallel): Clean fan-out to r1_bull and r1_bear, joined at moderator.
    Round 2+ (Sequential): Serial flow (bull -> bear -> moderator) for cross-review.
    """
    builder = StateGraph(
        DebateState,
        input=DebateInput,
        output=DebateOutput,
    )

    # 1. Add Nodes
    builder.add_node(
        "debate_aggregator", debate_aggregator_node, metadata={"agent_id": "debate"}
    )
    builder.add_node(
        "fact_extractor", fact_extractor_node, metadata={"agent_id": "debate"}
    )

    # Round 1 Agents (Parallel)
    builder.add_node(
        "r1_bull",
        r1_bull_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r1_bear",
        r1_bear_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r1_moderator",
        r1_moderator_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )

    # Round 2 Agents (Sequential)
    builder.add_node(
        "r2_bull",
        r2_bull_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r2_bear",
        r2_bear_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r2_moderator",
        r2_moderator_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )

    # Round 3 Agents (Sequential)
    builder.add_node(
        "r3_bull",
        r3_bull_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r3_bear",
        r3_bear_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )

    # Final Synthesis
    builder.add_node(
        "verdict",
        verdict_node,
        metadata={"agent_id": "debate"},
        retry=RetryPolicy(max_attempts=3),
    )

    # 2. Define Edges (Strict Linear DAG)
    builder.add_edge(START, "debate_aggregator")

    # Fan-out to Round 1 via Fact Extractor
    builder.add_edge("debate_aggregator", "fact_extractor")
    builder.add_edge("fact_extractor", "r1_bull")
    builder.add_edge("fact_extractor", "r1_bear")

    # Sync Round 1 at Moderator
    builder.add_edge(["r1_bull", "r1_bear"], "r1_moderator")

    # Transition to Round 2
    builder.add_edge("r1_moderator", "r2_bull")
    builder.add_edge("r2_bull", "r2_bear")
    builder.add_edge("r2_bear", "r2_moderator")

    # Transition to Round 3 (Swapped Order: Bear -> Bull)
    builder.add_edge("r2_moderator", "r3_bear")
    builder.add_edge("r3_bear", "r3_bull")

    # Final Verdict
    builder.add_edge("r3_bull", "verdict")
    builder.add_edge("verdict", END)

    return builder.compile()
