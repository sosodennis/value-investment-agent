from typing import Any

from src.interface.mappers import NodeOutputMapper
from src.interface.protocol import AgentEvent


def get_agent_name(metadata: dict | None = None) -> str:
    """
    Map internal node name to high-level agent name.

    Zero Config Policy:
    1. Check if 'agent_id' is present in metadata (Preferred)
    2. Fallback to 'System' if not found
    """
    if metadata and "agent_id" in metadata:
        return metadata["agent_id"]
    return "System"


def adapt_langgraph_event(
    event: dict, thread_id: str, seq_id: int, run_id: str = ""
) -> list[AgentEvent]:
    """
    Transforms a LangGraph v2 astream_events chunk into standardized AgentEvents.

    Architecture:
    1. Unwrap LangGraph Command objects (structural concern)
    2. Use NodeOutputMapper to transform nested state to flat UI payload (semantic concern)
    3. Emit standardized events
    """
    kind = event["event"]
    metadata = event.get("metadata", {})
    node_name = metadata.get("langgraph_node", "")
    tags = event.get("tags", []) or []

    # 1. Handle Tag-Based Stream Control
    # If a node is tagged with "hide_stream", we ignore its chat model streaming events
    if "hide_stream" in tags and kind == "on_chat_model_stream":
        return []

    # 2. Handle Token Streaming (Typewriter effect)
    if kind == "on_chat_model_stream":
        chunk = event["data"].get("chunk")
        if chunk and hasattr(chunk, "content") and chunk.content:
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
        raw_output = event["data"].get("output")

        # Step 1: Unwrap Command objects (LangGraph returns {update: {...}, goto: ...})
        output = raw_output
        if hasattr(raw_output, "update") and isinstance(raw_output.update, dict):
            output = raw_output.update
        elif isinstance(raw_output, dict) and "update" in raw_output:
            # Heuristic: if it has 'update' and 'goto', it's a serialized Command
            if "goto" in raw_output or "graph" in raw_output:
                output = raw_output["update"]

        # Ensure we have a dict to work with
        if not isinstance(output, dict):
            output = {}

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
            if "node_statuses" in output and isinstance(output["node_statuses"], dict):
                for node_id, status in output["node_statuses"].items():
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
        return [
            AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_id,
                type="error",
                source=get_agent_name(metadata),
                data={
                    "message": str(event.get("data", {}).get("error", "Unknown error"))
                },
            )
        ]

    return []


def create_interrupt_event(
    interrupt_payload: Any,
    thread_id: str,
    seq_id: int,
    run_id: str = "",
    source: str = "system.interrupt",
) -> AgentEvent:
    """Creates a standardized interrupt request event with UI schema if possible."""
    from src.workflow.interrupts import HumanApprovalRequest, HumanTickerSelection

    data = interrupt_payload

    # REFACTORED: Try to use generic to_ui_payload if available
    # Instead of hardcoding types, we check for the conversion method
    if hasattr(interrupt_payload, "to_ui_payload"):
        data = interrupt_payload.to_ui_payload()
    elif isinstance(interrupt_payload, dict):
        itype = interrupt_payload.get("type")
        try:
            # Fallback for raw dicts if they match known types
            if itype == "approval_request":
                data = HumanApprovalRequest.model_validate(
                    interrupt_payload
                ).to_ui_payload()
            elif itype == "ticker_selection":
                data = HumanTickerSelection.model_validate(
                    interrupt_payload
                ).to_ui_payload()
        except Exception as e:
            # Fallback to raw payload
            from src.common.utils.logger import get_logger

            get_logger(__name__).warning(
                f"⚠️ [Adapter] Failed to hydrate interrupt schema: {e}"
            )

    return AgentEvent(
        thread_id=thread_id,
        run_id=run_id,
        seq_id=seq_id,
        type="interrupt.request",
        source=source,
        data=data if isinstance(data, dict) else {"payload": data},
    )
