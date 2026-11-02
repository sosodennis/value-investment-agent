from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.debate.application.ports import DebateWorkflowPort
from src.llm_provider.entrypoint import LLMProviderError

from .nodes import build_debate_nodes
from .state import DebateInput, DebateOutput, DebateState

_ACTIVITY_METADATA = {
    "debate_aggregator": (("debate", "prepare-sources"), "Prepare debate sources"),
    "fact_extractor": (("debate", "extract-evidence"), "Extract evidence"),
    "r1_bull": (("debate", "bull-case-round-one"), "Build the bull case"),
    "r1_bear": (("debate", "bear-case-round-one"), "Build the bear case"),
    "r1_moderator": (("debate", "moderate-round-one"), "Moderate debate"),
    "r2_bull": (("debate", "bull-case-round-two"), "Refine the bull case"),
    "r2_bear": (("debate", "bear-case-round-two"), "Refine the bear case"),
    "r2_moderator": (("debate", "moderate-round-two"), "Moderate debate"),
    "r3_bull": (("debate", "bull-case-round-three"), "Finalize the bull case"),
    "r3_bear": (("debate", "bear-case-round-three"), "Finalize the bear case"),
    "verdict": (("debate", "moderate-verdict"), "Produce final verdict"),
}


def _retryable_provider_error(error: Exception) -> bool:
    return isinstance(error, LLMProviderError) and error.retryable


def build_debate_workflow(runner: DebateWorkflowPort) -> CompiledStateGraph:
    nodes = build_debate_nodes(runner)
    builder = StateGraph(
        DebateState,
        input_schema=DebateInput,
        output_schema=DebateOutput,
    )

    for name in ("debate_aggregator", "fact_extractor"):
        scope_path, activity_label = _ACTIVITY_METADATA[name]
        builder.add_node(
            name,
            nodes[name],
            metadata={
                "agent_id": "debate",
                "workflow_activity_kind": "node",
                "workflow_scope_path": scope_path,
                "activity_label": activity_label,
            },
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
        scope_path, activity_label = _ACTIVITY_METADATA[name]
        builder.add_node(
            name,
            node,
            metadata={
                "agent_id": "debate",
                "workflow_activity_kind": "node",
                "workflow_scope_path": scope_path,
                "activity_label": activity_label,
            },
            retry_policy=retry,
        )
    builder.add_node(
        "verdict",
        nodes["verdict"],
        metadata={
            "agent_id": "debate",
            "workflow_activity_kind": "node",
            "workflow_scope_path": _ACTIVITY_METADATA["verdict"][0],
            "activity_label": _ACTIVITY_METADATA["verdict"][1],
        },
        retry_policy=RetryPolicy(max_attempts=3, retry_on=_retryable_provider_error),
    )

    builder.add_edge(START, "debate_aggregator")
    return builder.compile()
