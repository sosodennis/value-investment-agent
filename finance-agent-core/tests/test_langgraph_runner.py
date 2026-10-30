import asyncio
from collections.abc import AsyncIterator, Mapping
from contextvars import Context
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Interrupt, interrupt

from src.analysis_runtime.domain.contracts import (
    Activity,
    InteractionRequested,
    WorkflowAgentOutput,
)
from src.analysis_runtime.domain.errors import (
    InvalidRunnerInterruptError,
    InvalidRunnerOutputError,
)
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


async def _run(
    events: list[Mapping[str, object]],
) -> list[Activity | InteractionRequested | WorkflowAgentOutput]:
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
async def test_runner_passes_explicit_retry_checkpoint_identity() -> None:
    graph = _EventGraph([])
    runner = LangGraphRunner(graph)
    checkpoint = {
        "namespace": "workflow:thread-1:run:source",
        "checkpoint_id": "checkpoint-42",
        "activity_id": "debate.verdict",
    }
    items = [
        item
        async for item in runner.run(
            thread_id="thread-1",
            run_id="retry-run-1",
            input_data={"retry": {"checkpoint": checkpoint}},
            principal_id="principal-1",
        )
    ]
    assert items == []
    assert graph.calls[0][0] is None
    assert graph.calls[0][1] == {
        "configurable": {
            "thread_id": "thread-1",
            "checkpoint_ns": checkpoint["namespace"],
            "checkpoint_id": checkpoint["checkpoint_id"],
        }
    }


@pytest.mark.asyncio
async def test_runner_collapses_same_scope_wrappers_and_keeps_children_under_visible_parent() -> (
    None
):
    events = [
        {
            "event": "on_chain_start",
            "run_id": "agent-wrapper",
            "parent_ids": [],
            "metadata": _metadata(
                agent_id="intent_extraction",
                langgraph_node="intent_agent",
                agent_node="intent_agent",
                agent_scope="agent",
            ),
        },
        {
            "event": "on_chain_start",
            "run_id": "agent-wrapper-child",
            "parent_ids": ["agent-wrapper"],
            "metadata": _metadata(
                agent_id="intent_extraction",
                langgraph_node="intent_agent",
                agent_node="intent_agent",
                agent_scope="agent",
            ),
        },
        {
            "event": "on_chain_start",
            "run_id": "extraction-node",
            "parent_ids": ["agent-wrapper", "agent-wrapper-child"],
            "metadata": _metadata(
                agent_id="intent_extraction", langgraph_node="extraction"
            ),
        },
        {
            "event": "on_chain_end",
            "run_id": "extraction-node",
            "parent_ids": ["agent-wrapper", "agent-wrapper-child"],
            "metadata": _metadata(
                agent_id="intent_extraction", langgraph_node="extraction"
            ),
        },
        {
            "event": "on_chain_end",
            "run_id": "agent-wrapper-child",
            "parent_ids": ["agent-wrapper"],
            "metadata": _metadata(
                agent_id="intent_extraction",
                langgraph_node="intent_agent",
                agent_node="intent_agent",
                agent_scope="agent",
            ),
        },
        {
            "event": "on_chain_end",
            "run_id": "agent-wrapper",
            "parent_ids": [],
            "metadata": _metadata(
                agent_id="intent_extraction",
                langgraph_node="intent_agent",
                agent_node="intent_agent",
                agent_scope="agent",
            ),
        },
    ]

    activities = await _run(events)

    assert [activity.activity_id for activity in activities] == [
        "langgraph:agent-wrapper",
        "langgraph:extraction-node",
        "langgraph:extraction-node",
        "langgraph:agent-wrapper",
    ]
    assert activities[1].parent_activity_id == "langgraph:agent-wrapper"
    assert activities[2].status == "completed"


@pytest.mark.asyncio
async def test_runner_assigns_interrupt_to_visible_parent_of_same_scope_wrapper() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "clarifying-parent",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="intent_extraction", langgraph_node="clarifying"
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "clarifying-wrapper",
                "parent_ids": ["clarifying-parent"],
                "metadata": _metadata(
                    agent_id="intent_extraction", langgraph_node="clarifying"
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "clarifying-stream",
                "parent_ids": ["clarifying-parent", "clarifying-wrapper"],
                "metadata": _metadata(
                    agent_id="intent_extraction", langgraph_node="clarifying"
                ),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="interaction-wrapper-1",
                                value={
                                    "type": "ticker_selection",
                                    "reason": "Choose the intended company.",
                                    "candidates": [
                                        {
                                            "symbol": "AAPL",
                                            "name": "Apple Inc.",
                                            "confidence": 0.99,
                                        }
                                    ],
                                },
                            ),
                        )
                    }
                },
            },
        ]
    )

    projected = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="thread-1",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    assert len(projected) == 2
    assert isinstance(projected[0], Activity)
    assert isinstance(projected[1], InteractionRequested)
    assert projected[1].activity.activity_id == projected[0].activity_id


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
async def test_runner_emits_compact_output_on_completed_agent_subgraph() -> None:
    items = await _run(
        [
            {
                "event": "on_chain_end",
                "run_id": "intent-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="intent_extraction",
                    agent_scope="agent",
                    agent_node="intent_agent",
                    langgraph_node="intent_agent",
                ),
                "data": {
                    "output": {
                        "intent_extraction": {
                            "artifact": {
                                "kind": "intent_extraction.output",
                                "version": "v1",
                                "summary": "Resolved AAPL",
                                "preview": {"ticker": "AAPL"},
                                "reference": {
                                    "artifact_id": "artifact-1",
                                    "type": "intent_report",
                                },
                            }
                        }
                    }
                },
            }
        ]
    )

    assert len(items) == 2
    activity, output = items
    assert isinstance(activity, Activity)
    assert activity.status == "completed"
    assert isinstance(output, WorkflowAgentOutput)
    assert output.identity.thread_id == "thread-1"
    assert output.identity.run_id == "runtime-run-1"
    assert output.identity.activity_id == activity.activity_id
    assert output.agent_id == "intent_extraction"
    assert output.output_kind == "intent_extraction.output"
    assert output.preview == {"ticker": "AAPL"}
    assert output.artifact_id == "artifact-1"
    assert output.artifact_type == "intent_report"


@pytest.mark.asyncio
async def test_runner_rejects_oversized_preview_without_artifact_reference() -> None:
    with pytest.raises(InvalidRunnerOutputError, match="artifact reference"):
        await _run(
            [
                {
                    "event": "on_chain_end",
                    "run_id": "news-node",
                    "parent_ids": [],
                    "metadata": _metadata(
                        agent_id="financial_news_research",
                        agent_scope="agent",
                        agent_node="news_agent",
                        langgraph_node="news_agent",
                    ),
                    "data": {
                        "output": {
                            "financial_news_research": {
                                "artifact": {
                                    "kind": "financial_news_research.output",
                                    "version": "v1",
                                    "summary": "News report",
                                    "preview": {"large": "x" * (17 * 1024)},
                                }
                            }
                        }
                    },
                }
            ]
        )


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
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.activity_id == "langgraph:clarifying-node"
    assert waiting.activity.status == "waiting"
    assert waiting.identity.interaction_id == "interaction-1"
    assert waiting.request.candidates[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_runner_projects_versioned_valuation_approval_interrupt() -> None:
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="approval-1",
                                value={
                                    "type": "valuation_approval",
                                    "contract_version": "v1",
                                    "ticker": "AAPL",
                                    "model_type": "dcf_growth",
                                    "title": "Review valuation assumptions",
                                    "description": "Approve before deterministic calculation.",
                                    "parameters": {"wacc": 0.09},
                                    "audit_messages": ["PASS: parameters are valid"],
                                },
                            ),
                        )
                    }
                },
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

    assert isinstance(activities[-1], InteractionRequested)
    waiting = activities[-1]
    assert waiting.request.type == "valuation_approval"
    assert waiting.request.contract_version == "v1"
    assert waiting.request.parameters == {"wacc": 0.09}


@pytest.mark.asyncio
async def test_runner_assigns_interrupt_to_event_callback_when_parallel_callbacks_are_active() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "news-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="financial_news_research",
                    langgraph_node="news_agent",
                    agent_scope="agent",
                    agent_node="news_agent",
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="approval-parallel-1",
                                value={
                                    "type": "valuation_approval",
                                    "contract_version": "v1",
                                    "ticker": "AAPL",
                                    "model_type": "dcf_standard",
                                    "title": "Review valuation assumptions",
                                    "description": "Approve before deterministic calculation.",
                                    "parameters": {"wacc": 0.09},
                                    "audit_messages": [],
                                },
                            ),
                        )
                    }
                },
            },
        ]
    )

    activities = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="parallel-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.activity_id == "langgraph:calculation-node"
    assert waiting.activity.scope_path == ("fundamental_analysis", "calculation")


@pytest.mark.asyncio
async def test_runner_uses_nearest_active_parent_for_bubbled_parallel_interrupt() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "news-node",
                "parent_ids": ["workflow-root"],
                "metadata": _metadata(
                    agent_id="financial_news_research",
                    langgraph_node="news_agent",
                    agent_scope="agent",
                    agent_node="news_agent",
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "calculation-node",
                "parent_ids": ["workflow-root"],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "nested-graph-stream",
                "parent_ids": ["workflow-root", "calculation-node"],
                "metadata": {"langgraph_checkpoint_ns": "nested"},
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="approval-bubbled-parallel-1",
                                value={
                                    "type": "valuation_approval",
                                    "contract_version": "v1",
                                    "ticker": "AAPL",
                                    "model_type": "dcf_standard",
                                    "title": "Review valuation assumptions",
                                    "description": "Approve before deterministic calculation.",
                                    "parameters": {"wacc": 0.09},
                                    "audit_messages": [],
                                },
                            ),
                        )
                    }
                },
            },
        ]
    )

    activities = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="parallel-bubbled-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.activity_id == "langgraph:calculation-node"
    assert waiting.activity.scope_path == ("fundamental_analysis", "calculation")


@pytest.mark.asyncio
async def test_runner_assigns_unscoped_interrupt_by_typed_owner_with_parallel_agents() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "news-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="financial_news_research",
                    langgraph_node="news_agent",
                    agent_scope="agent",
                    agent_node="news_agent",
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "bubbled-calculation-stream",
                "parent_ids": [],
                "metadata": {"langgraph_checkpoint_ns": "nested"},
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="approval-unscoped-parallel-1",
                                value={
                                    "type": "valuation_approval",
                                    "contract_version": "v1",
                                    "ticker": "AAPL",
                                    "model_type": "dcf_standard",
                                    "title": "Review valuation assumptions",
                                    "description": "Approve before deterministic calculation.",
                                    "parameters": {"wacc": 0.09},
                                    "audit_messages": [],
                                },
                            ),
                        )
                    }
                },
            },
        ]
    )

    activities = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="parallel-unscoped-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.activity_id == "langgraph:calculation-node"
    assert waiting.activity.scope_path == ("fundamental_analysis", "calculation")


@pytest.mark.asyncio
async def test_runner_uses_interrupt_scope_when_inner_callback_id_is_not_active() -> (
    None
):
    graph = _EventGraph(
        [
            {
                "event": "on_chain_start",
                "run_id": "news-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="financial_news_research",
                    langgraph_node="news_agent",
                    agent_scope="agent",
                    agent_node="news_agent",
                ),
            },
            {
                "event": "on_chain_start",
                "run_id": "calculation-node",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
            },
            {
                "event": "on_chain_stream",
                "run_id": "nested-graph-stream",
                "parent_ids": [],
                "metadata": _metadata(
                    agent_id="fundamental_analysis",
                    langgraph_node="calculation",
                ),
                "data": {
                    "chunk": {
                        "__interrupt__": (
                            Interrupt(
                                id="approval-nested-stream-1",
                                value={
                                    "type": "valuation_approval",
                                    "contract_version": "v1",
                                    "ticker": "AAPL",
                                    "model_type": "dcf_standard",
                                    "title": "Review valuation assumptions",
                                    "description": "Approve before deterministic calculation.",
                                    "parameters": {"wacc": 0.09},
                                    "audit_messages": [],
                                },
                            ),
                        )
                    }
                },
            },
        ]
    )

    activities = [
        item
        async for item in LangGraphRunner(graph).run(
            thread_id="nested-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "Apple"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.activity_id == "langgraph:calculation-node"
    assert waiting.activity.scope_path == ("fundamental_analysis", "calculation")


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
        provider_principal = get_provider_principal()
        request_principal = get_request_principal()
        assert provider_principal is not None
        assert provider_principal.user_id == "principal-1"
        assert request_principal is not None
        assert request_principal.subject_id == "principal-1"
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

    first_stream = runner.run(
        thread_id="real-interrupt-thread",
        run_id="runtime-run-1",
        input_data={"message": "Apple"},
        principal_id="principal-1",
    )
    consumer_context = Context()
    first = []
    while True:
        item = await asyncio.create_task(anext(first_stream), context=consumer_context)
        first.append(item)
        if isinstance(item, InteractionRequested):
            break
    assert consumer_context.run(get_provider_principal) is None
    assert consumer_context.run(get_request_principal) is None
    await asyncio.create_task(first_stream.aclose(), context=Context())

    waiting = first[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.status == "waiting"
    assert waiting.activity.scope_path == ("clarifying",)
    assert waiting.request.candidates[0].symbol == "AAPL"

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
                "resuming_activity_id": waiting.activity.activity_id,
                "resuming_scope_path": list(waiting.activity.scope_path),
                "resuming_attempt": waiting.activity.attempt,
            },
            principal_id="principal-1",
        )
    ]
    resumed_activity = next(
        item
        for item in resumed
        if isinstance(item, Activity)
        and item.activity_id == waiting.activity.activity_id
    )
    assert resumed_activity.status == "completed"
    assert resumed_activity.attempt == waiting.activity.attempt + 1
    assert all(not isinstance(item, InteractionRequested) for item in resumed)


@pytest.mark.asyncio
async def test_runner_assigns_bubbled_interrupt_to_nested_agent_node() -> None:
    class State(TypedDict, total=False):
        selected: str

    async def clarify(state: State) -> dict[str, object]:
        selection = interrupt(
            {
                "type": "ticker_selection",
                "reason": "Choose the intended company.",
                "candidates": [
                    {"symbol": "AAPL", "name": "Apple Inc.", "confidence": 0.96},
                    {
                        "symbol": "AAPL.TO",
                        "name": "Apple Canada",
                        "confidence": 0.62,
                    },
                ],
            }
        )
        return {"selected": selection["selected_symbol"]}

    child_builder = StateGraph(State)
    child_builder.add_node("clarifying", clarify)
    child_builder.add_edge(START, "clarifying")
    child_builder.add_edge("clarifying", END)

    root_builder = StateGraph(State)
    root_builder.add_node(
        "intent_agent",
        child_builder.compile(),
        metadata={
            "agent_id": "intent_extraction",
            "agent_scope": "agent",
            "agent_node": "intent_agent",
        },
    )
    root_builder.add_edge(START, "intent_agent")
    root_builder.add_edge("intent_agent", END)
    runner = LangGraphRunner(root_builder.compile(checkpointer=MemorySaver()))

    activities = [
        item
        async for item in runner.run(
            thread_id="nested-interrupt-thread",
            run_id="runtime-run-1",
            input_data={"message": "AAPL"},
            principal_id="principal-1",
        )
    ]

    waiting = activities[-1]
    assert isinstance(waiting, InteractionRequested)
    assert waiting.activity.status == "waiting"
    assert waiting.activity.scope_path == ("intent_extraction", "clarifying")
    assert [candidate.symbol for candidate in waiting.request.candidates] == [
        "AAPL",
        "AAPL.TO",
    ]
