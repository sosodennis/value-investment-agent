from collections.abc import Mapping

from langchain_core.messages import AIMessageChunk
from langgraph.types import Command
from pydantic import BaseModel

from src.interface.events.mappers import NodeOutputMapper
from src.interface.events.protocol import AgentEvent
from src.shared.kernel.types import JSONObject


def get_agent_name(metadata: Mapping[str, object] | None = None) -> str:
    """
    Map internal node name to high-level agent name.

    Zero Config Policy:
    1. Check if 'agent_id' is present in metadata (Preferred)
    2. Fallback to 'System' if not found
    """
    if metadata and "agent_id" in metadata:
        return metadata["agent_id"]
    return "System"


def is_agent_boundary(metadata: Mapping[str, object] | None = None) -> bool:
    """
    Identify top-level agent boundaries to avoid emitting lifecycle events
    for internal subgraph nodes.
    """
    if not metadata:
        return False
    if metadata.get("agent_scope") != "agent":
        return False
    node_name = metadata.get("langgraph_node")
    boundary_node = metadata.get("agent_node")
    if not isinstance(node_name, str) or not isinstance(boundary_node, str):
        return False
    return node_name == boundary_node


def _iter_mappings(value: object) -> list[Mapping[str, object]]:
    stack: list[object] = [value]
    mappings: list[Mapping[str, object]] = []
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            mappings.append(current)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return mappings


def _has_error_logs(output: Mapping[str, object]) -> bool:
    error_logs = output.get("error_logs")
    if not isinstance(error_logs, list):
        return False
    for entry in error_logs:
        if not isinstance(entry, Mapping):
            continue
        severity = entry.get("severity")
        if isinstance(severity, str) and severity.lower() == "error":
            return True
    return False


def _has_degraded_flags(output: Mapping[str, object]) -> bool:
    for mapping in _iter_mappings(output):
        is_degraded = mapping.get("is_degraded")
        if isinstance(is_degraded, bool) and is_degraded:
            return True
        degraded_reasons = mapping.get("degraded_reasons")
        if isinstance(degraded_reasons, list) and degraded_reasons:
            return True
        quality_gates = mapping.get("quality_gates") or mapping.get(
            "xbrl_quality_gates"
        )
        if isinstance(quality_gates, Mapping):
            gate_degraded = quality_gates.get("is_degraded")
            if isinstance(gate_degraded, bool) and gate_degraded:
                return True
    return False


def _derive_agent_lifecycle_status(
    output: Mapping[str, object], agent_id: str | None
) -> str:
    if _has_error_logs(output):
        return "error"

    explicit_status = None
    agent_statuses_raw = output.get("agent_statuses")
    if isinstance(agent_statuses_raw, Mapping) and agent_id:
        status_raw = agent_statuses_raw.get(agent_id)
        if isinstance(status_raw, str):
            explicit_status = status_raw

    if explicit_status in {"error", "degraded", "attention"}:
        return explicit_status
    if _has_degraded_flags(output):
        return "degraded"
    if explicit_status == "done":
        return "done"
    return "done"


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    """Normalize allowed structured outputs into a mapping for downstream mappers."""
    if isinstance(value, Mapping):
        return value
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise TypeError(
                f"{context} BaseModel must dump to dict, got {type(dumped)!r}"
            )
        return dumped
    raise TypeError(f"{context} must be Mapping|BaseModel, got {type(value)!r}")


def adapt_langgraph_event(
    event: Mapping[str, object], thread_id: str, seq_id: int, run_id: str = ""
) -> list[AgentEvent]:
    """
    Transforms a LangGraph v2 astream_events chunk into standardized AgentEvents.

    Architecture:
    1. Unwrap LangGraph Command objects (structural concern)
    2. Use NodeOutputMapper to transform nested state to flat UI payload (semantic concern)
    3. Emit standardized events
    """
    kind = event.get("event")
    if not isinstance(kind, str):
        raise TypeError("Invalid LangGraph event: missing string 'event'")

    metadata_raw = event.get("metadata")
    metadata: Mapping[str, object] = (
        metadata_raw if isinstance(metadata_raw, Mapping) else {}
    )
    node_name_raw = metadata.get("langgraph_node")
    node_name = node_name_raw if isinstance(node_name_raw, str) else ""

    tags_raw = event.get("tags")
    tags = tags_raw if isinstance(tags_raw, list) else []

    # 1. Handle Tag-Based Stream Control
    # If a node is tagged with "hide_stream", we ignore its chat model streaming events
    if "hide_stream" in tags and kind == "on_chat_model_stream":
        return []

    # 2. Handle Token Streaming (Typewriter effect)
    if kind == "on_chat_model_stream":
        data_raw = event.get("data")
        if not isinstance(data_raw, Mapping):
            return []
        chunk = data_raw.get("chunk")
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            return [
                AgentEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    seq_id=seq_id,
                    type="content.delta",
                    source=get_agent_name(metadata),
                    data={"content": str(chunk.content)},
                )
            ]

    # 2. Handle Agent Status Changes
    elif kind == "on_chain_start":
        agent_id = get_agent_name(metadata)
        if agent_id and agent_id != "System":
            events = [
                AgentEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    seq_id=seq_id,
                    type="agent.status",
                    source=agent_id,
                    data={"status": "running", "node": node_name},
                )
            ]
            if is_agent_boundary(metadata):
                events.append(
                    AgentEvent(
                        thread_id=thread_id,
                        run_id=run_id,
                        seq_id=seq_id + 1,
                        type="agent.lifecycle",
                        source=agent_id,
                        data={"status": "running"},
                    )
                )
            return events

    elif kind == "on_chain_end":
        agent_id = get_agent_name(metadata)
        data_raw = event.get("data")
        if not isinstance(data_raw, Mapping):
            raise TypeError("Invalid on_chain_end event: 'data' must be a mapping")
        raw_output = data_raw.get("output")

        # Step 1: Unwrap Command objects (LangGraph returns {update: {...}, goto: ...})
        output: Mapping[str, object]
        if isinstance(raw_output, Command):
            output = _as_mapping(raw_output.update, "on_chain_end Command.update")
        elif isinstance(raw_output, Mapping):
            update_raw = raw_output.get("update")
            if update_raw is not None:
                output = _as_mapping(update_raw, "on_chain_end output.update")
            else:
                output = _as_mapping(raw_output, "on_chain_end output")
        elif isinstance(raw_output, BaseModel):
            output = _as_mapping(raw_output, "on_chain_end output")
        else:
            raise TypeError(f"Invalid on_chain_end output type: {type(raw_output)!r}")

        events = []
        emitted_status_for_agent = False
        is_boundary = is_agent_boundary(metadata)

        # Step 2: Transform nested state to UI payload using mapper
        if agent_id and agent_id != "System":
            ui_payload = NodeOutputMapper.transform(agent_id, output)

            if ui_payload:
                events.append(
                    AgentEvent(
                        thread_id=thread_id,
                        run_id=run_id,
                        seq_id=seq_id,
                        type="state.update",
                        source=agent_id,
                        data=ui_payload,
                    )
                )
                seq_id += 1

            # 3. Explicit Status Emission (Restored Logic)
            # If the output contains explicit `node_statuses`, we must emit agent.status events.
            # This replaces the old "auto-done" logic with "explicit-done" logic.
            node_statuses_raw = output.get("node_statuses")
            if isinstance(node_statuses_raw, Mapping):
                for node_id, status in node_statuses_raw.items():
                    if not isinstance(node_id, str) or not isinstance(status, str):
                        raise TypeError("node_statuses must be a mapping[str, str]")
                    events.append(
                        AgentEvent(
                            thread_id=thread_id,
                            run_id=run_id,
                            seq_id=seq_id,
                            type="agent.status",
                            source=node_id,  # Status updates are typically keyed by agent_id (e.g. "intent_extraction")
                            data={"status": status, "node": node_name},
                        )
                    )
                    seq_id += 1
                    if node_id == agent_id:
                        emitted_status_for_agent = True

            if is_boundary:
                lifecycle_status = _derive_agent_lifecycle_status(output, agent_id)
                events.append(
                    AgentEvent(
                        thread_id=thread_id,
                        run_id=run_id,
                        seq_id=seq_id,
                        type="agent.lifecycle",
                        source=agent_id,
                        data={"status": lifecycle_status},
                    )
                )
                seq_id += 1

            if not emitted_status_for_agent:
                events.append(
                    AgentEvent(
                        thread_id=thread_id,
                        run_id=run_id,
                        seq_id=seq_id,
                        type="agent.status",
                        source=agent_id,
                        data={"status": "done", "node": node_name},
                    )
                )
                seq_id += 1

        return events

    # 3. Handle Errors
    elif kind == "on_chain_error":
        data_raw = event.get("data")
        error_message = "Unknown error"
        if isinstance(data_raw, Mapping):
            err_raw = data_raw.get("error")
            if err_raw is not None:
                error_message = str(err_raw)
        agent_id = get_agent_name(metadata)
        events = [
            AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_id,
                type="error",
                source=agent_id,
                data={"message": error_message},
            )
        ]
        if agent_id and agent_id != "System":
            events.append(
                AgentEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    seq_id=seq_id + 1,
                    type="agent.status",
                    source=agent_id,
                    data={"status": "error", "node": node_name},
                )
            )
            if is_agent_boundary(metadata):
                events.append(
                    AgentEvent(
                        thread_id=thread_id,
                        run_id=run_id,
                        seq_id=seq_id + 2,
                        type="agent.lifecycle",
                        source=agent_id,
                        data={"status": "error"},
                    )
                )
        return events

    return []


def create_interrupt_event(
    interrupt_payload: object,
    thread_id: str,
    seq_id: int,
    run_id: str = "",
    source: str = "system.interrupt",
) -> AgentEvent:
    """Creates a standardized interrupt request event with strict payload schema."""
    if not isinstance(interrupt_payload, Mapping):
        raise TypeError(f"Invalid interrupt payload type: {type(interrupt_payload)!r}")
    interrupt_type = interrupt_payload.get("type")
    if interrupt_type != "ticker_selection":
        raise TypeError(f"Unsupported interrupt type: {interrupt_type!r}")

    candidates = interrupt_payload.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("ticker_selection interrupt must contain a candidates list")

    ticker_options: list[str] = []
    ticker_titles: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypeError("Each candidate must be a mapping")
        symbol = candidate.get("symbol")
        name = candidate.get("name")
        confidence = candidate.get("confidence")
        if not isinstance(symbol, str) or not isinstance(name, str):
            raise TypeError("Candidate symbol/name must be strings")
        confidence_pct = 0.0
        if isinstance(confidence, int | float):
            confidence_pct = confidence * 100
        ticker_options.append(symbol)
        ticker_titles.append(f"{symbol} - {name} ({confidence_pct:.0f}% match)")

    reason = interrupt_payload.get("reason")
    description = (
        reason
        if isinstance(reason, str)
        else "Multiple tickers found or ambiguity detected."
    )

    data: JSONObject = {
        "type": "ticker_selection",
        "title": "Ticker Resolution",
        "description": description,
        "data": {},
        "schema": {
            "title": "Select Correct Ticker",
            "type": "object",
            "properties": {
                "selected_symbol": {
                    "type": "string",
                    "title": "Target Company",
                    "enum": ticker_options,
                    "oneOf": [
                        {"const": symbol, "title": ticker_titles[idx]}
                        for idx, symbol in enumerate(ticker_options)
                    ],
                }
            },
            "required": ["selected_symbol"],
        },
        "ui_schema": {"selected_symbol": {"ui:widget": "radio"}},
    }

    return AgentEvent(
        thread_id=thread_id,
        run_id=run_id,
        seq_id=seq_id,
        type="interrupt.request",
        source=source,
        data=data,
    )
