from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.debate.application.ports import DebateWorkflowPort
from src.llm_provider.entrypoint import LLMProviderError

from .nodes import build_debate_nodes
from .state import DebateInput, DebateOutput, DebateState


def _retryable_provider_error(error: Exception) -> bool:
    return isinstance(error, LLMProviderError) and error.retryable


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
    ):
        node = nodes[name]
        builder.add_node(
            name, node, metadata={"agent_id": "debate"}, retry_policy=retry
        )
    builder.add_node(
        "verdict",
        nodes["verdict"],
        metadata={"agent_id": "debate"},
        retry_policy=RetryPolicy(max_attempts=3, retry_on=_retryable_provider_error),
    )

    builder.add_edge(START, "debate_aggregator")
    return builder.compile()
