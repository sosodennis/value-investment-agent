from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from api.server import active_tasks, app
from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeCursorRecord,
    WorkspaceRuntimeRunStatusRecord,
)


@pytest.mark.asyncio
async def test_thread_state_returns_rehydration_fields_for_workspace_refresh() -> None:
    thread_id = "thread_refresh_restore"
    activity_records = [
        WorkspaceRuntimeActivityRecord(
            event_id="evt-1",
            thread_id=thread_id,
            seq_id=5,
            run_id="run-1",
            agent_id="intent_extraction",
            node="intent_extraction",
            event_type="agent.lifecycle",
            status="running",
            payload={},
            created_at=datetime(2026, 3, 21, 12, 0),
        ),
        WorkspaceRuntimeActivityRecord(
            event_id="evt-2",
            thread_id=thread_id,
            seq_id=4,
            run_id="run-1",
            agent_id="intent_extraction",
            node="intent_extraction",
            event_type="agent.status",
            status="running",
            payload={},
            created_at=datetime(2026, 3, 21, 11, 59),
        ),
    ]
    cursor_record = WorkspaceRuntimeCursorRecord(
        thread_id=thread_id,
        last_seq_id=5,
        updated_at=datetime(2026, 3, 21, 12, 5),
    )
    run_record = WorkspaceRuntimeRunStatusRecord(
        thread_id=thread_id,
        run_id="run-1",
        status="running",
        started_at=datetime(2026, 3, 21, 12, 0),
        updated_at=datetime(2026, 3, 21, 12, 5),
        ended_at=None,
        last_seq_id=5,
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

    class _FakeRuntimeProjection:
        async def fetch_recent_activity(
            self,
            *,
            thread_id: str,
            limit: int = 50,
        ) -> list[WorkspaceRuntimeActivityRecord]:
            return activity_records

        async def fetch_latest_statuses(
            self,
            *,
            thread_id: str,
        ) -> dict[str, str]:
            return {
                "intent_extraction": "running",
                "fundamental_analysis": "idle",
            }

        async def fetch_latest_lifecycle_statuses(
            self,
            *,
            thread_id: str,
        ) -> dict[str, str]:
            return {
                "intent_extraction": "running",
                "fundamental_analysis": "idle",
            }

        async def fetch_cursor(
            self,
            *,
            thread_id: str,
        ) -> WorkspaceRuntimeCursorRecord:
            return cursor_record

        async def fetch_run_status(
            self,
            *,
            thread_id: str,
        ) -> WorkspaceRuntimeRunStatusRecord | None:
            return run_record

    had_graph = hasattr(app.state, "graph")
    previous_graph = getattr(app.state, "graph", None)
    had_projection = hasattr(app.state, "runtime_projection")
    previous_projection = getattr(app.state, "runtime_projection", None)
    app.state.graph = _FakeGraph()
    app.state.runtime_projection = _FakeRuntimeProjection()
    active_tasks[thread_id] = object()  # type: ignore[assignment]

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
        assert payload["cursor"]["last_seq_id"] == 5
        assert payload["active_agent_id"] == "intent_extraction"
        assert len(payload["activity_timeline"]) == 2
        assert payload["activity_timeline"][0]["event_type"] == "agent.lifecycle"
        assert len(payload["status_history"]) == 1
        assert payload["status_history"][0]["agentId"] == "intent_extraction"
        assert payload["messages"][1]["agentId"] == "intent_extraction"
        assert payload["agent_statuses"]["intent_extraction"] == "running"
        assert payload["run"]["run_id"] == "run-1"
        assert payload["run"]["status"] == "running"
    finally:
        active_tasks.pop(thread_id, None)
        if had_graph:
            app.state.graph = previous_graph
        elif hasattr(app.state, "graph"):
            delattr(app.state, "graph")
        if had_projection:
            app.state.runtime_projection = previous_projection
        elif hasattr(app.state, "runtime_projection"):
            delattr(app.state, "runtime_projection")


@pytest.mark.asyncio
async def test_agent_activity_endpoint_returns_recent_agent_events() -> None:
    thread_id = "thread_activity"
    records = [
        WorkspaceRuntimeActivitySegmentRecord(
            segment_id="segment-1",
            thread_id=thread_id,
            agent_id="intent_extraction",
            node="intent_extraction",
            run_id="run-1",
            status="done",
            started_at=datetime(2026, 3, 21, 12, 0),
            updated_at=datetime(2026, 3, 21, 12, 5),
            ended_at=datetime(2026, 3, 21, 12, 5),
            last_seq_id=2,
        ),
        WorkspaceRuntimeActivitySegmentRecord(
            segment_id="segment-2",
            thread_id=thread_id,
            agent_id="intent_extraction",
            node="clarifying",
            run_id="run-1",
            status="running",
            started_at=datetime(2026, 3, 21, 12, 6),
            updated_at=datetime(2026, 3, 21, 12, 7),
            ended_at=None,
            last_seq_id=3,
        ),
    ]

    class _FakeRuntimeProjection:
        async def fetch_activity_segments(
            self,
            *,
            thread_id: str,
            agent_id: str,
            limit: int = 5,
            before_updated_at: datetime | None = None,
        ) -> list[WorkspaceRuntimeActivitySegmentRecord]:
            assert thread_id == "thread_activity"
            assert agent_id == "intent_extraction"
            assert limit == 2
            assert before_updated_at is None
            return records

    had_projection = hasattr(app.state, "runtime_projection")
    previous_projection = getattr(app.state, "runtime_projection", None)
    app.state.runtime_projection = _FakeRuntimeProjection()

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/thread/{thread_id}/activity",
                params={"agent_id": "intent_extraction", "limit": 2},
            )

        assert response.status_code == 200
        payload = response.json()
        assert [entry["id"] for entry in payload] == ["segment-2", "segment-1"]
        assert payload[0]["agentId"] == "intent_extraction"
        assert payload[0]["status"] == "running"
        assert payload[0]["is_current"] is True
    finally:
        if had_projection:
            app.state.runtime_projection = previous_projection
        elif hasattr(app.state, "runtime_projection"):
            delattr(app.state, "runtime_projection")
