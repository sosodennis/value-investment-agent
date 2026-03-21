from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from api.server import (
    active_tasks,
    app,
    event_replay_buffers,
    thread_sequences,
)
from src.interface.events.protocol import AgentEvent


@pytest.mark.asyncio
async def test_thread_state_returns_rehydration_fields_for_workspace_refresh() -> None:
    thread_id = "thread_refresh_restore"
    replay_event = AgentEvent(
        thread_id=thread_id,
        run_id="run-1",
        seq_id=5,
        type="agent.status",
        source="intent_extraction",
        data={"status": "running", "node": "intent_extraction"},
    )
    snapshot = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(content="Valuate AAPL"),
                AIMessage(
                    content="Resolving ticker",
                    additional_kwargs={"type": "text", "agentId": "intent_extraction"},
                ),
            ],
            "node_statuses": {
                "intent_extraction": "running",
                "fundamental_analysis": "idle",
            },
            "current_node": "intent_extraction",
            "fundamental_analysis": {"resolved_ticker": "AAPL", "status": "running"},
        },
        tasks=[],
        next=("fundamental_analysis",),
    )

    class _FakeGraph:
        async def aget_state(self, _config: object) -> SimpleNamespace:
            return snapshot

    had_graph = hasattr(app.state, "graph")
    previous_graph = getattr(app.state, "graph", None)
    app.state.graph = _FakeGraph()
    active_tasks[thread_id] = object()  # type: ignore[assignment]
    event_replay_buffers[thread_id] = [f"data: {replay_event.model_dump_json()}\n\n"]
    thread_sequences[thread_id] = 6

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(f"/thread/{thread_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["current_node"] == "intent_extraction"
        assert payload["current_status"] == "running"
        assert payload["last_seq_id"] == 5
        assert len(payload["status_history"]) == 1
        assert payload["status_history"][0]["agentId"] == "intent_extraction"
        assert payload["messages"][1]["agentId"] == "intent_extraction"
    finally:
        active_tasks.pop(thread_id, None)
        event_replay_buffers.pop(thread_id, None)
        thread_sequences.pop(thread_id, None)
        if had_graph:
            app.state.graph = previous_graph
        elif hasattr(app.state, "graph"):
            delattr(app.state, "graph")
