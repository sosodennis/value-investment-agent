from __future__ import annotations

from datetime import datetime

from api.server import (
    _build_event_from_activity_record,
    _format_sse_event,
    _parse_after_seq,
)
from src.interface.events.protocol import AgentEvent
from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
)


def test_parse_after_seq_prefers_query_param() -> None:
    assert _parse_after_seq(after_seq=10, last_event_id="5") == 10


def test_parse_after_seq_uses_last_event_id_when_missing() -> None:
    assert _parse_after_seq(after_seq=None, last_event_id="7") == 7
    assert _parse_after_seq(after_seq=None, last_event_id="bad") is None


def test_format_sse_event_includes_id_event_and_data() -> None:
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=3,
        type="agent.status",
        source="intent_extraction",
        data={"status": "running"},
    )

    payload = _format_sse_event(event)

    assert "id: 3" in payload
    assert "event: agent.status" in payload
    assert "data:" in payload
    assert '"seq_id":' in payload
    assert '"seq_id":3' in payload.replace(" ", "")


def test_build_event_from_activity_record_roundtrip() -> None:
    record = WorkspaceRuntimeActivityRecord(
        event_id="evt-1",
        thread_id="thread-1",
        seq_id=4,
        run_id="run-1",
        agent_id="system",
        node=None,
        event_type="lifecycle.status",
        status="done",
        payload={"data": {"status": "done"}, "metadata": {"source": "test"}},
        created_at=datetime(2026, 3, 21, 12, 0),
    )

    event = _build_event_from_activity_record(record)

    assert event.id == "evt-1"
    assert event.seq_id == 4
    assert event.type == "lifecycle.status"
    assert event.source == "system"
    assert event.data == {"status": "done"}
    assert event.metadata == {"source": "test"}
