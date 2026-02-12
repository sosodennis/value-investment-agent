from collections.abc import Mapping

from langchain_core.messages import AIMessageChunk
from langgraph.types import Command
from pydantic import BaseModel

from src.common.types import JSONObject
from src.interface.mappers import NodeOutputMapper
from src.interface.protocol import AgentEvent


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
            return [
                AgentEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    seq_id=seq_id,
                    type="agent.status",
                    source=agent_id,
                    data={"status": "running", "node": node_name},
                )
            ]

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

        return events

    # 3. Handle Errors
    elif kind == "on_chain_error":
        data_raw = event.get("data")
        error_message = "Unknown error"
        if isinstance(data_raw, Mapping):
            err_raw = data_raw.get("error")
            if err_raw is not None:
                error_message = str(err_raw)
        return [
            AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_id,
                type="error",
                source=get_agent_name(metadata),
                data={"message": error_message},
            )
        ]

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
                    "enumNames": ticker_titles,
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
