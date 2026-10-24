from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Literal, Protocol
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.analysis_runtime.application.ports import GraphRunner
from src.analysis_runtime.domain.contracts import Activity, ActivityKind, ActivityStatus


class EventGraph(Protocol):
    def astream_events(
        self,
        input_data: Command[object] | dict[str, object],
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
    ) -> AsyncIterator[Mapping[str, object]]: ...


_LIFECYCLE_EVENTS: dict[
    str, tuple[Literal["chain", "tool", "model"], ActivityStatus]
] = {
    "on_chain_start": ("chain", "running"),
    "on_chain_end": ("chain", "completed"),
    "on_chain_error": ("chain", "failed"),
    "on_tool_start": ("tool", "running"),
    "on_tool_end": ("tool", "completed"),
    "on_tool_error": ("tool", "failed"),
    "on_chat_model_start": ("model", "running"),
    "on_chat_model_end": ("model", "completed"),
    "on_chat_model_error": ("model", "failed"),
    "on_llm_start": ("model", "running"),
    "on_llm_end": ("model", "completed"),
    "on_llm_error": ("model", "failed"),
}


def _callback_id(value: object) -> str | None:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _activity_scope(metadata: Mapping[str, object]) -> tuple[str, ...]:
    """Build public scope from application agent and graph-node metadata only."""
    agent_id = metadata.get("agent_id")
    node_id = metadata.get("langgraph_node")
    if not isinstance(node_id, str) or not node_id.strip():
        node_id = metadata.get("agent_node")
    return tuple(
        value.strip()
        for value in (agent_id, node_id)
        if isinstance(value, str) and value.strip()
    )


def _activity_attempt(metadata: Mapping[str, object]) -> int:
    attempt = metadata.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0:
        return attempt
    return 1


def _activity_progress(
    raw: Mapping[str, object], metadata: Mapping[str, object]
) -> float | int | None:
    for source in (metadata, raw):
        for key in ("activity_progress", "progress"):
            value = source.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                if 0 <= value <= 100:
                    return value
    return None


def _activity_kind(event_type: str, metadata: Mapping[str, object]) -> ActivityKind:
    event_family, _ = _LIFECYCLE_EVENTS[event_type]
    if event_family == "tool":
        return "tool"
    if (
        event_family == "chain"
        and metadata.get("agent_scope") == "agent"
        and metadata.get("langgraph_node") == metadata.get("agent_node")
    ):
        return "subgraph"
    return "node"


def _activity_label(
    event_type: str, metadata: Mapping[str, object], scope_path: tuple[str, ...]
) -> str:
    label = metadata.get("activity_label")
    if isinstance(label, str) and label.strip():
        return label.strip()[:160]
    if len(scope_path) > 1:
        return scope_path[-1][:160]
    if scope_path:
        return scope_path[0][:160]
    event_family, _ = _LIFECYCLE_EVENTS[event_type]
    return {"tool": "Tool invocation", "model": "Model invocation"}.get(
        event_family, "Workflow activity"
    )


class LangGraphRunner(GraphRunner):
    """Translate LangGraph lifecycle callbacks to application activities."""

    def __init__(self, graph: EventGraph) -> None:
        self._graph = graph

    async def run(
        self,
        *,
        thread_id: str,
        run_id: str,
        input_data: Mapping[str, object],
        principal_id: str,
    ) -> AsyncIterator[Activity]:
        message = input_data.get("message")
        resume_payload = input_data.get("resume_payload")
        if isinstance(message, str) and message:
            graph_input: Command[object] | dict[str, object] = {
                "messages": [HumanMessage(content=message)],
                "user_query": message,
            }
        elif isinstance(resume_payload, Mapping):
            graph_input = Command(resume=dict(resume_payload))
        else:
            graph_input = {}

        callback_metadata: dict[str, Mapping[str, object]] = {}
        async for raw in self._graph.astream_events(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            event_name = raw.get("event")
            if not isinstance(event_name, str) or event_name not in _LIFECYCLE_EVENTS:
                continue
            metadata = raw.get("metadata")
            metadata_map = metadata if isinstance(metadata, Mapping) else {}
            callback_run_id = _callback_id(raw.get("run_id"))
            if callback_run_id in callback_metadata:
                merged_metadata = dict(callback_metadata[callback_run_id])
                merged_metadata.update(metadata_map)
                metadata_map = merged_metadata
            scope_path = _activity_scope(metadata_map)
            if callback_run_id is None or not scope_path:
                continue
            callback_metadata[callback_run_id] = metadata_map

            parent_activity_id = None
            parent_ids = raw.get("parent_ids")
            if isinstance(parent_ids, list | tuple):
                for parent_id in reversed(parent_ids):
                    normalized_parent_id = _callback_id(parent_id)
                    if normalized_parent_id is not None:
                        parent_activity_id = f"langgraph:{normalized_parent_id}"
                        break

            _, status = _LIFECYCLE_EVENTS[event_name]
            yield Activity(
                activity_id=f"langgraph:{callback_run_id}",
                parent_activity_id=parent_activity_id,
                thread_id=thread_id,
                run_id=run_id,
                scope_path=scope_path,
                kind=_activity_kind(event_name, metadata_map),
                status=status,
                label=_activity_label(event_name, metadata_map, scope_path),
                progress=_activity_progress(raw, metadata_map),
                attempt=_activity_attempt(metadata_map),
            )
