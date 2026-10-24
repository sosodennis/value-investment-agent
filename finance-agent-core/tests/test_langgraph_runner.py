from collections.abc import AsyncIterator, Mapping

import pytest

from src.analysis_runtime.domain.contracts import Activity
from src.analysis_runtime.infrastructure.langgraph_runner import LangGraphRunner


class _EventGraph:
    def __init__(self, events: list[Mapping[str, object]]) -> None:
        self.events = events
        self.calls: list[tuple[object, object, str]] = []

    async def astream_events(
        self,
        input_data: object,
        config: object = None,
        *,
        version: str = "v2",
    ) -> AsyncIterator[Mapping[str, object]]:
        self.calls.append((input_data, config, version))
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
