from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Literal, Protocol
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langgraph.types import Interrupt as LangGraphInterrupt

from src.analysis_runtime.application.ports import GraphRunner
from src.analysis_runtime.domain.contracts import (
    MAX_AGENT_OUTPUT_PREVIEW_BYTES,
    Activity,
    ActivityKind,
    ActivityStatus,
    InteractionIdentity,
    InteractionRequested,
    TickerSelectionRequest,
    ValuationApprovalRequest,
    WorkflowActivityIdentity,
    WorkflowAgentOutput,
)
from src.analysis_runtime.domain.errors import (
    InvalidRunnerInterruptError,
    InvalidRunnerOutputError,
)
from src.llm_provider.entrypoint import (
    ProviderPrincipal,
    reset_provider_principal,
    set_provider_principal,
)
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)


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


_AGENT_OUTPUT_CONTEXTS = {
    "intent_extraction": "intent_extraction",
    "fundamental_analysis": "fundamental_analysis",
    "financial_news_research": "financial_news_research",
    "technical_analysis": "technical_analysis",
    "debate": "debate",
}


def _completed_agent_output(
    raw: Mapping[str, object],
    metadata: Mapping[str, object],
    *,
    thread_id: str,
    run_id: str,
    activity_id: str,
    scope_path: tuple[str, ...],
) -> WorkflowAgentOutput | None:
    agent_id = metadata.get("agent_id")
    if (
        metadata.get("agent_scope") != "agent"
        or metadata.get("langgraph_node") != metadata.get("agent_node")
        or not isinstance(agent_id, str)
        or agent_id not in _AGENT_OUTPUT_CONTEXTS
        or not scope_path
        or scope_path[0] != agent_id
    ):
        return None
    data = raw.get("data")
    output = data.get("output") if isinstance(data, Mapping) else None
    if not isinstance(output, Mapping):
        return None
    context = output.get(_AGENT_OUTPUT_CONTEXTS[agent_id])
    if not isinstance(context, Mapping):
        context = output
    artifact = context.get("artifact")
    if not isinstance(artifact, Mapping):
        return None
    artifact_data = dict(artifact)
    preview = artifact_data.get("preview")
    if isinstance(preview, Mapping):
        try:
            preview_size = len(
                json.dumps(
                    preview,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise InvalidRunnerOutputError(
                "agent output preview is not finite JSON"
            ) from exc
        if preview_size > MAX_AGENT_OUTPUT_PREVIEW_BYTES:
            reference = artifact_data.get("reference")
            if not isinstance(reference, Mapping) or not isinstance(
                reference.get("artifact_id"), str
            ):
                raise InvalidRunnerOutputError(
                    "oversized agent output requires an artifact reference"
                )
            artifact_data["preview"] = None
    reference = artifact_data.get("reference")
    artifact_id = None
    artifact_type = None
    if isinstance(reference, Mapping):
        raw_artifact_id = reference.get("artifact_id")
        if isinstance(raw_artifact_id, str) and raw_artifact_id:
            artifact_id = raw_artifact_id
        raw_artifact_type = reference.get("type")
        if isinstance(raw_artifact_type, str) and raw_artifact_type:
            artifact_type = raw_artifact_type
    try:
        return WorkflowAgentOutput(
            identity=WorkflowActivityIdentity(
                thread_id=thread_id,
                run_id=run_id,
                activity_id=activity_id,
            ),
            agent_id=agent_id,
            output_kind=str(artifact_data["kind"]),
            output_version=str(artifact_data["version"]),
            summary=str(artifact_data["summary"]),
            preview=(
                dict(artifact_data["preview"])
                if isinstance(artifact_data.get("preview"), Mapping)
                else None
            ),
            artifact_id=artifact_id,
            artifact_type=artifact_type,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidRunnerOutputError(
            "agent output artifact has an invalid contract"
        ) from exc


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
    ) -> AsyncIterator[Activity | InteractionRequested | WorkflowAgentOutput]:
        message = input_data.get("message")
        interrupt_response = input_data.get("interrupt_response")
        resuming_activity_id = input_data.get("resuming_activity_id")
        resuming_scope_path = input_data.get("resuming_scope_path")
        resuming_attempt = input_data.get("resuming_attempt")
        if isinstance(resuming_scope_path, list | tuple) and all(
            isinstance(part, str) for part in resuming_scope_path
        ):
            resume_scope = tuple(resuming_scope_path)
        else:
            resume_scope = ()
        if not isinstance(resuming_activity_id, str):
            resuming_activity_id = None
        if not isinstance(resuming_attempt, int) or isinstance(resuming_attempt, bool):
            resuming_attempt = 0
        if isinstance(message, str) and message:
            graph_input: Command[object] | dict[str, object] = {
                "messages": [HumanMessage(content=message)],
                "user_query": message,
            }
        elif isinstance(interrupt_response, Mapping):
            graph_input = Command(resume=dict(interrupt_response))
        else:
            graph_input = {}

        provider_token = set_provider_principal(ProviderPrincipal(user_id=principal_id))
        request_token = set_request_principal(
            InternalPrincipal(subject_id=principal_id)
        )
        try:
            callback_metadata: dict[str, Mapping[str, object]] = {}
            active_callbacks: dict[
                str, tuple[Mapping[str, object], tuple[str, ...], str | None]
            ] = {}
            resumed_activity_started = False
            suspended = False
            async for raw in self._graph.astream_events(
                graph_input,
                config={"configurable": {"thread_id": thread_id}},
                version="v2",
            ):
                if suspended:
                    continue
                event_name = raw.get("event")
                if event_name == "on_chain_stream":
                    interruption = self._interrupt_activity(
                        raw,
                        thread_id=thread_id,
                        run_id=run_id,
                        resuming_activity_id=resuming_activity_id,
                        resuming_scope_path=resume_scope,
                        resuming_attempt=resuming_attempt,
                        active_callbacks=active_callbacks,
                    )
                    if interruption is not None:
                        suspended = True
                        yield interruption
                    continue
                if (
                    not isinstance(event_name, str)
                    or event_name not in _LIFECYCLE_EVENTS
                ):
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

                is_resumed_activity = (
                    not resumed_activity_started
                    and resuming_activity_id is not None
                    and scope_path == resume_scope
                )
                activity_id = (
                    resuming_activity_id
                    if is_resumed_activity
                    else f"langgraph:{callback_run_id}"
                )
                attempt = (
                    resuming_attempt + 1
                    if is_resumed_activity
                    else _activity_attempt(metadata_map)
                )
                parent_activity_id = None
                parent_ids = raw.get("parent_ids")
                if isinstance(parent_ids, list | tuple):
                    for parent_id in reversed(parent_ids):
                        normalized_parent_id = _callback_id(parent_id)
                        if normalized_parent_id is not None:
                            parent_activity_id = f"langgraph:{normalized_parent_id}"
                            break

                event_family, status = _LIFECYCLE_EVENTS[event_name]
                if event_family == "chain" and event_name == "on_chain_start":
                    active_callbacks[callback_run_id] = (
                        metadata_map,
                        scope_path,
                        parent_activity_id,
                    )

                if is_resumed_activity and status == "running":
                    continue
                if is_resumed_activity:
                    resumed_activity_started = True

                activity = Activity(
                    activity_id=activity_id,
                    parent_activity_id=parent_activity_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    scope_path=scope_path,
                    kind=_activity_kind(event_name, metadata_map),
                    status=status,
                    label=_activity_label(event_name, metadata_map, scope_path),
                    progress=_activity_progress(raw, metadata_map),
                    attempt=attempt,
                )
                yield activity
                if event_name == "on_chain_end":
                    output = _completed_agent_output(
                        raw,
                        metadata_map,
                        thread_id=thread_id,
                        run_id=run_id,
                        activity_id=activity_id,
                        scope_path=scope_path,
                    )
                    if output is not None:
                        yield output
                if event_family == "chain" and event_name in {
                    "on_chain_end",
                    "on_chain_error",
                }:
                    active_callbacks.pop(callback_run_id, None)
        finally:
            reset_request_principal(request_token)
            reset_provider_principal(provider_token)

    @staticmethod
    def _interrupt_activity(
        raw: Mapping[str, object],
        *,
        thread_id: str,
        run_id: str,
        resuming_activity_id: str | None,
        resuming_scope_path: tuple[str, ...],
        resuming_attempt: int,
        active_callbacks: Mapping[
            str, tuple[Mapping[str, object], tuple[str, ...], str | None]
        ],
    ) -> InteractionRequested | None:
        data = raw.get("data")
        chunk = data.get("chunk") if isinstance(data, Mapping) else None
        if not isinstance(chunk, Mapping) or "__interrupt__" not in chunk:
            return None
        raw_interrupts = chunk.get("__interrupt__")
        if not isinstance(raw_interrupts, list | tuple) or len(raw_interrupts) != 1:
            raise InvalidRunnerInterruptError(
                "interrupt stream must contain one request"
            )
        interrupt = raw_interrupts[0]
        if not isinstance(interrupt, LangGraphInterrupt):
            raise InvalidRunnerInterruptError("interrupt stream has an invalid request")
        value = interrupt.value
        if not isinstance(value, Mapping):
            raise InvalidRunnerInterruptError("interrupt request must be an object")
        try:
            if value.get("type") == "ticker_selection":
                request = TickerSelectionRequest.model_validate(
                    {
                        "type": "ticker_selection",
                        "title": "Ticker Resolution",
                        "description": value.get("reason"),
                        "candidates": value.get("candidates"),
                    }
                )
            elif value.get("type") == "valuation_approval":
                request = ValuationApprovalRequest.model_validate(value)
            else:
                raise InvalidRunnerInterruptError("unsupported interrupt request type")
        except InvalidRunnerInterruptError:
            raise
        except Exception as exc:
            raise InvalidRunnerInterruptError(
                "interrupt request has an invalid payload"
            ) from exc

        interrupt_callback_id = _callback_id(raw.get("run_id"))
        interrupt_owner = (
            "intent_extraction"
            if request.type == "ticker_selection"
            else "fundamental_analysis"
        )
        scoped_callbacks = [
            (callback_id, callback)
            for callback_id, callback in active_callbacks.items()
            if callback[1]
        ]
        typed_owner_callbacks = [
            (callback_id, callback)
            for callback_id, callback in scoped_callbacks
            if callback[1][0] == interrupt_owner
        ]
        owner_callbacks = typed_owner_callbacks or (
            scoped_callbacks if len(scoped_callbacks) == 1 else []
        )
        direct_callback = next(
            (
                (callback_id, callback)
                for callback_id, callback in owner_callbacks
                if callback_id == interrupt_callback_id
            ),
            None,
        )
        raw_parent_ids = raw.get("parent_ids")
        parent_callbacks = []
        if isinstance(raw_parent_ids, list | tuple):
            for parent_id in raw_parent_ids:
                normalized_parent_id = _callback_id(parent_id)
                if normalized_parent_id is None:
                    continue
                callback = active_callbacks.get(normalized_parent_id)
                if (
                    callback is not None
                    and callback[1]
                    and callback[1][0] == interrupt_owner
                ):
                    parent_callbacks.append((normalized_parent_id, callback))
        interrupt_metadata = raw.get("metadata")
        interrupt_metadata_map = (
            interrupt_metadata if isinstance(interrupt_metadata, Mapping) else {}
        )
        interrupt_scope = _activity_scope(interrupt_metadata_map)
        scope_callbacks = [
            (callback_id, callback)
            for callback_id, callback in owner_callbacks
            if interrupt_scope
            and (
                callback[1] == interrupt_scope
                or callback[1][-len(interrupt_scope) :] == interrupt_scope
            )
        ]
        if direct_callback is not None:
            selected_callbacks = [direct_callback]
        elif parent_callbacks:
            # Stream events can bubble an interrupt from a nested graph whose
            # run_id is not an activity callback. The nearest active parent is
            # the authoritative owner when unrelated graph branches are active.
            selected_callbacks = [parent_callbacks[-1]]
        elif scope_callbacks:
            selected_callbacks = scope_callbacks
        elif owner_callbacks:
            selected_callbacks = owner_callbacks
        else:
            diagnostics = {
                "interrupt_run_id": interrupt_callback_id,
                "interrupt_parent_ids": [
                    value for value in raw_parent_ids if isinstance(value, str | UUID)
                ][:20]
                if isinstance(raw_parent_ids, list | tuple)
                else [],
                "interrupt_scope": list(interrupt_scope),
                "interrupt_owner": interrupt_owner,
                "candidate_callback_ids": [
                    callback_id for callback_id, _ in scoped_callbacks
                ][:20],
                "candidate_scopes": [
                    {"callback_id": callback_id, "scope": list(callback[1])}
                    for callback_id, callback in scoped_callbacks[:20]
                ],
            }
            raise InvalidRunnerInterruptError(
                "interrupt has no active application activity",
                diagnostics=diagnostics,
            )

        def callback_depth(
            callback: tuple[Mapping[str, object], tuple[str, ...], str | None],
        ) -> int:
            depth = 0
            parent_activity_id = callback[2]
            visited: set[str] = set()
            while parent_activity_id is not None:
                parent_callback_id = parent_activity_id.removeprefix("langgraph:")
                if (
                    parent_callback_id not in active_callbacks
                    or parent_callback_id in visited
                ):
                    break
                visited.add(parent_callback_id)
                depth += 1
                parent_activity_id = active_callbacks[parent_callback_id][2]
            return depth

        deepest_scope_depth = max(
            len(callback[1]) for _, callback in selected_callbacks
        )
        most_specific_callbacks = [
            (callback_id, callback)
            for callback_id, callback in selected_callbacks
            if len(callback[1]) == deepest_scope_depth
        ]
        deepest_callback_depth = max(
            callback_depth(callback) for _, callback in most_specific_callbacks
        )
        deepest_callbacks = [
            (callback_id, callback)
            for callback_id, callback in most_specific_callbacks
            if callback_depth(callback) == deepest_callback_depth
        ]
        if len({callback[1] for _, callback in deepest_callbacks}) > 1:
            raise InvalidRunnerInterruptError(
                "interrupt cannot be assigned to one active application activity",
                diagnostics={
                    "interrupt_run_id": interrupt_callback_id,
                    "interrupt_parent_ids": [
                        value
                        for value in raw_parent_ids
                        if isinstance(value, str | UUID)
                    ][:20]
                    if isinstance(raw_parent_ids, list | tuple)
                    else [],
                    "interrupt_scope": list(interrupt_scope),
                    "interrupt_owner": interrupt_owner,
                    "candidate_callback_ids": [
                        callback_id for callback_id, _ in deepest_callbacks
                    ][:20],
                    "candidate_scopes": [
                        {"callback_id": callback_id, "scope": list(callback[1])}
                        for callback_id, callback in deepest_callbacks[:20]
                    ],
                },
            )
        callback_run_id, (metadata_map, scope_path, parent_activity_id) = (
            deepest_callbacks[-1]
        )

        is_resumed_activity = (
            resuming_activity_id is not None and scope_path == resuming_scope_path
        )
        activity = Activity(
            activity_id=(
                resuming_activity_id
                if is_resumed_activity
                else f"langgraph:{callback_run_id}"
            ),
            parent_activity_id=parent_activity_id,
            thread_id=thread_id,
            run_id=run_id,
            scope_path=scope_path,
            kind=_activity_kind("on_chain_start", metadata_map),
            status="waiting",
            label=_activity_label("on_chain_start", metadata_map, scope_path),
            attempt=(
                resuming_attempt + 1
                if is_resumed_activity
                else _activity_attempt(metadata_map)
            ),
        )
        return InteractionRequested(
            activity=activity,
            identity=InteractionIdentity(
                thread_id=thread_id,
                run_id=run_id,
                activity_id=activity.activity_id,
                interaction_id=interrupt.id,
            ),
            request=request,
        )
