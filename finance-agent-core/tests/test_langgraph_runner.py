from collections.abc import AsyncIterator, Mapping
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Interrupt, interrupt

from src.analysis_runtime.domain.contracts import Activity
from src.analysis_runtime.domain.errors import InvalidRunnerInterruptError
from src.analysis_runtime.infrastructure.langgraph_runner import LangGraphRunner
from src.llm_provider.entrypoint import get_provider_principal
from src.shared.internal_services import get_request_principal


class _EventGraph:
    def __init__(self, events: list[Mapping[str, object]]) -> None:
        self.events = events
        self.calls: list[tuple[object, object, str]] = []
        self.principals: list[tuple[object, object]] = []

    async def astream_events(
        self,
        input_data: object,
        config: object = None,
        *,
        version: str = "v2",
    ) -> AsyncIterator[Mapping[str, object]]:
        self.calls.append((input_data, config, version))
        self.principals.append((get_provider_principal(), get_request_principal()))
        for event in self.events:
            yield event


def _metadata(**values: object) -> dict[str, object]:
    return {
        "agent_id": "news",
        "langgraph_node": "fetch",
        "langgraph_checkpoint_ns": "private-checkpoint-namespace",
        **values,
    }


async def _run(events: list[Mapping[str, object]]) -> list[Activity]:
    runner = LangGraphRunner(_EventGraph(events))
    return [
        activity
        async for activity in runner.run(
            thread_id="thread-1",
            run_id="runtime-run-1",
            input_data={"message": "find news"},
            principal_id="principal-1",
        )
    ]


@pytest.mark.asyncio
async def test_runner_uses_callback_ids_and_parent_ids_for_repeated_invocations() -> (
    None
):
    activities = await _run(
        [
            {
                "event": "on_chain_start",
                "run_id": "parent-node",
                "parent_ids": [],
                "metadata": _metadata(
                    langgraph_node="news_agent",
                    agent_node="news_agent",
                    agent_scope="agent",
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "node-1",
                "parent_ids": ["parent-node"],
                "metadata": _metadata(activity_label="First fetch"),
            },
            {
                "event": "on_chain_end",
                "run_id": "node-1",
                "parent_ids": ["parent-node"],
                "metadata": _metadata(progress=71, activity_progress=37),
            },
            {
                "event": "on_chain_start",
                "run_id": "node-2",
                "parent_ids": ["parent-node"],
                "metadata": _metadata(attempt=2),
            },
            {
                "event": "on_tool_start",
                "run_id": "tool-1",
                "parent_ids": ["node-2"],
                "metadata": _metadata(langgraph_node="search_provider"),
            },
        ]
    )

    assert [activity.activity_id for activity in activities] == [
        "langgraph:parent-node",
        "langgraph:node-1",
        "langgraph:node-1",
        "langgraph:node-2",
        "langgraph:tool-1",
    ]
    assert activities[0].parent_activity_id is None
    assert activities[0].kind == "subgraph"
    assert activities[1].parent_activity_id == "langgraph:parent-node"
    assert activities[3].parent_activity_id == "langgraph:parent-node"
    assert activities[4].parent_activity_id == "langgraph:node-2"
    assert activities[1].status == "running"
    assert activities[2].status == "completed"
    assert activities[3].attempt == 2
    assert activities[2].progress == 37
    assert activities[1].progress is None
    assert all(
        "private-checkpoint-namespace" not in part
        for activity in activities
        for part in activity.scope_path
    )


@pytest.mark.asyncio
async def test_runner_scopes_authenticated_principal_for_internal_service_clients() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "node-1",
                "parent_ids": [],
                "metadata": _metadata(),
            }
        ]
    )
    runner = LangGraphRunner(graph)

    [
        _
        async for _ in runner.run(
            thread_id="thread-1",
            run_id="runtime-run-1",
            input_data={"message": "find news"},
            principal_id="principal-1",
        )
    ]

    provider_principal, request_principal = graph.principals[0]
    assert provider_principal.user_id == "principal-1"
    assert request_principal.subject_id == "principal-1"
    assert get_provider_principal() is None
    assert get_request_principal() is None


@pytest.mark.asyncio
async def test_runner_emits_tool_and_model_lifecycle_events_but_skips_stream_chunks() -> (
    None
):
    activities = await _run(
        [
            {
                "event": "on_chain_start",
                "run_id": "node-1",
                "parent_ids": [],
                "metadata": _metadata(),
            },
            {
                "event": "on_chat_model_start",
                "run_id": "model-1",
                "parent_ids": ["node-1"],
                "metadata": _metadata(langgraph_node="summarize"),
            },
            {
                "event": "on_chat_model_stream",
                "run_id": "model-1",
                "parent_ids": ["node-1"],
                "metadata": _metadata(langgraph_node="summarize"),
                "data": {"chunk": "token"},
            },
            {
                "event": "on_chat_model_end",
                "run_id": "model-1",
                "parent_ids": ["node-1"],
                "metadata": _metadata(langgraph_node="summarize"),
            },
            {
                "event": "on_tool_start",
                "run_id": "tool-1",
                "parent_ids": ["model-1"],
                "metadata": _metadata(langgraph_node="search_provider"),
            },
            {
                "event": "on_tool_error",
                "run_id": "tool-1",
                "parent_ids": ["model-1"],
                "metadata": _metadata(langgraph_node="search_provider"),
            },
            {
                "event": "on_chain_stream",
                "run_id": "node-1",
                "parent_ids": [],
                "metadata": _metadata(),
            },
        ]
    )

    assert len(activities) == 5
    assert [activity.kind for activity in activities] == [
        "node",
        "node",
        "node",
        "tool",
        "tool",
    ]
    assert [activity.status for activity in activities] == [
        "running",
        "running",
        "completed",
        "running",
        "failed",
    ]
    assert activities[1].activity_id == activities[2].activity_id
    assert activities[1].parent_activity_id == "langgraph:node-1"
    assert activities[3].parent_activity_id == "langgraph:model-1"
    assert all(activity.progress is None for activity in activities)


@pytest.mark.asyncio
async def test_runner_projects_typed_interrupt_and_stops_at_suspension() -> None:
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "clarifying-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="intent_extraction",
                    langgraph_node="clarifying",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "clarifying-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="intent_extraction",
                    langgraph_node="clarifying",
                ),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="interaction-1",
                                value={
                                    "type": "ticker_selection",
                                    "reason": "Choose the intended company.",
                                    "candidates": [
                                        {
                                            "symbol": "AAPL",
                                            "name": "Apple Inc.",
                                            "confidence": 0.96,
                                        }
                                    ],
                                },
                            ),
                        )
                    }
                },
            },
            {
                "event": "on_chain_end",
                "run_id": "clarifying-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="intent_extraction",
                    langgraph_node="clarifying",
                ),
            },
        ]
    )

    activities = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="thread-1",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert len(activities) == 2
    assert waiting.activity_id == "langgraph:clarifying-node"
    assert waiting.status == "waiting"
    assert waiting.interruption is not None
    assert waiting.interruption.interaction_id == "interaction-1"
    assert waiting.interruption.request.candidates[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_runner_rejects_unsupported_interrupt_payload() -> None:
    graph = _EventGraph(
        [
            {
                "event": "on_chain_stream",
                "run_id": "clarifying-node",
                "metadata": _metadata(langgraph_node="clarifying"),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(id="bad", value={"type": "approval"}),
                        )
                    }
                },
            }
        ]
    )

    with pytest.raises(InvalidRunnerInterruptError):
        [
            item
            async for item in LangGraphRunner(graph).run(
                thread_id="thread-1",
                run_id="runtime-run-1",
                input_data={"message": "Apple"},
                principal_id="principal-1",
            )
        ]


@pytest.mark.asyncio
async def test_runner_uses_pinned_langgraph_stream_for_wait_and_resume() -> None:
    class State(TypedDict, total=False):
        selected: str

    async def clarify(state: State) -> dict[str, object]:
        selection = interrupt(
            {
                "type": "ticker_selection",
                "reason": "Choose the intended company.",
                "candidates": [
                    {"symbol": "AAPL", "name": "Apple Inc.", "confidence": 0.96}
                ],
            }
        )
        return {"selected": selection["selected_symbol"]}

    builder = StateGraph(State)
    builder.add_node("clarifying", clarify)
    builder.add_edge(START, "clarifying")
    builder.add_edge("clarifying", END)
    runner = LangGraphRunner(builder.compile(checkpointer=MemorySaver()))

    first = [
        item
        async for item in runner.run(
            thread_id="real-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]
    waiting = first[-1]
    assert waiting.status == "waiting"
    assert waiting.scope_path == ("clarifying",)
    assert waiting.interruption is not None
    assert waiting.interruption.request.candidates[0].symbol == "AAPL"

    resumed = [
        item
        async for item in runner.run(
            thread_id="real-interrupt-thread",
            run_id="runtime-run-1",
            input_data={
                "interrupt_response": {
                    "type": "ticker_selection",
                    "selected_symbol": "AAPL",
                },
                "resuming_activity_id": waiting.activity_id,
                "resuming_scope_path": list(waiting.scope_path),
                "resuming_attempt": waiting.attempt,
            },
            principal_id="principal-1",
        )
    ]
    resumed_activity = next(
        item for item in resumed if item.activity_id == waiting.activity_id
    )
    assert resumed_activity.status == "running"
    assert resumed_activity.attempt == waiting.attempt + 1
    assert all(item.interruption is None for item in resumed)
