"""
Debate subgraph entrypoint owned by the debate agent package.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from src.workflow.nodes.debate.nodes import (
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
from src.workflow.nodes.debate.subgraph_state import (
    DebateInput,
    DebateOutput,
    DebateState,
)


def build_debate_subgraph():
    """
    Build and return the cognitive debate sub-graph with blind debate mechanism.
    """
    builder = StateGraph(
        DebateState,
        input_schema=DebateInput,
        output_schema=DebateOutput,
    )

    builder.add_node(
        "debate_aggregator", debate_aggregator_node, metadata={"agent_id": "debate"}
    )
    builder.add_node(
        "fact_extractor", fact_extractor_node, metadata={"agent_id": "debate"}
    )

    builder.add_node(
        "r1_bull",
        r1_bull_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r1_bear",
        r1_bear_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r1_moderator",
        r1_moderator_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_node(
        "r2_bull",
        r2_bull_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r2_bear",
        r2_bear_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r2_moderator",
        r2_moderator_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_node(
        "r3_bull",
        r3_bull_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "r3_bear",
        r3_bear_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_node(
        "verdict",
        verdict_node,
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_edge(START, "debate_aggregator")
    builder.add_edge("debate_aggregator", "fact_extractor")
    builder.add_edge("fact_extractor", "r1_bull")
    builder.add_edge("fact_extractor", "r1_bear")
    builder.add_edge(["r1_bull", "r1_bear"], "r1_moderator")
    builder.add_edge("r1_moderator", "r2_bull")
    builder.add_edge("r2_bull", "r2_bear")
    builder.add_edge("r2_bear", "r2_moderator")
    builder.add_edge("r2_moderator", "r3_bear")
    builder.add_edge("r3_bear", "r3_bull")
    builder.add_edge("r3_bull", "verdict")
    builder.add_edge("verdict", END)

    return builder.compile()
