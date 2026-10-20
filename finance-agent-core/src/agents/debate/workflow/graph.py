from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.debate.application.ports import DebateWorkflowPort

from .nodes import build_debate_nodes
from .state import DebateInput, DebateOutput, DebateState


def build_debate_workflow(runner: DebateWorkflowPort) -> CompiledStateGraph:
    nodes = build_debate_nodes(runner)
    builder = StateGraph(
        DebateState,
        input_schema=DebateInput,
        output_schema=DebateOutput,
    )

    builder.add_node(
        "debate_aggregator", nodes["debate_aggregator"], metadata={"agent_id": "debate"}
    )
    builder.add_node(
        "fact_extractor", nodes["fact_extractor"], metadata={"agent_id": "debate"}
    )
    retry = RetryPolicy(max_attempts=3)
    for name in (
        "r1_bull",
        "r1_bear",
        "r1_moderator",
        "r2_bull",
        "r2_bear",
        "r2_moderator",
        "r3_bull",
        "r3_bear",
        "verdict",
    ):
        node = nodes[name]
        builder.add_node(
            name, node, metadata={"agent_id": "debate"}, retry_policy=retry
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
