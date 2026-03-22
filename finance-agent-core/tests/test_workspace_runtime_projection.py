from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import UniqueConstraint

from src.infrastructure.database import Base
from src.infrastructure.models import (
    ChatMessage,
    WorkspaceRuntimeActivityEvent,
    WorkspaceRuntimeActivitySegment,
    WorkspaceRuntimeCursor,
    WorkspaceRuntimeRunStatus,
)
from src.runtime.workspace_runtime_projection import (
    SqlAlchemyWorkspaceRuntimeProjectionRepository,
    WorkspaceRuntimeActivityRecord,
    derive_active_agent_id,
    derive_recent_activity,
    project_activity_segment,
    project_run_status,
)


def _record(
    *,
    event_id: str,
    seq_id: int,
    agent_id: str,
    status: str | None,
    created_at: datetime,
) -> WorkspaceRuntimeActivityRecord:
    return WorkspaceRuntimeActivityRecord(
        event_id=event_id,
        thread_id="thread-1",
        seq_id=seq_id,
        run_id="run-1",
        agent_id=agent_id,
        node="node-1",
        event_type="agent.status",
        status=status,
        payload={},
        created_at=created_at,
    )


def test_workspace_runtime_projection_models_registered_in_metadata() -> None:
    tables = Base.metadata.tables

    assert WorkspaceRuntimeActivityEvent.__tablename__ in tables
    assert WorkspaceRuntimeActivitySegment.__tablename__ in tables
    assert WorkspaceRuntimeCursor.__tablename__ in tables
    assert WorkspaceRuntimeRunStatus.__tablename__ in tables
    assert ChatMessage.__tablename__ in tables

    activity_table = tables[WorkspaceRuntimeActivityEvent.__tablename__]
    segment_table = tables[WorkspaceRuntimeActivitySegment.__tablename__]
    cursor_table = tables[WorkspaceRuntimeCursor.__tablename__]
    run_status_table = tables[WorkspaceRuntimeRunStatus.__tablename__]
    chat_table = tables[ChatMessage.__tablename__]

    assert "agent_id" in chat_table.c

    unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in activity_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("thread_id", "seq_id") in unique_constraints

    assert cursor_table.primary_key is not None
    assert segment_table.primary_key is not None
    assert run_status_table.primary_key is not None


@pytest.mark.asyncio
async def test_repository_appends_activity_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.committed = False

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            self.committed = True

    class _FakeSessionContext:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    fake_session = _FakeSession()

    monkeypatch.setattr(
        "src.runtime.workspace_runtime_projection.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(fake_session),
    )

    repository = SqlAlchemyWorkspaceRuntimeProjectionRepository()
    record = _record(
        event_id="evt-1",
        seq_id=42,
        agent_id="intent_extraction",
        status="running",
        created_at=datetime(2026, 3, 21, 12, 0),
    )

    await repository.append_activity_event(record)

    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    model = fake_session.added[0]
    assert isinstance(model, WorkspaceRuntimeActivityEvent)
    assert model.event_id == "evt-1"
    assert model.seq_id == 42
    assert model.agent_id == "intent_extraction"


@pytest.mark.asyncio
async def test_repository_fetches_activity_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updated_at = datetime(2026, 3, 21, 12, 30)
    model = WorkspaceRuntimeActivitySegment(
        segment_id="segment-1",
        thread_id="thread-1",
        agent_id="fundamental_analysis",
        node="fundamental_analysis",
        run_id="run-2",
        status="running",
        started_at=updated_at,
        updated_at=updated_at,
        ended_at=None,
        last_seq_id=7,
    )

    class _ExecuteResult:
        def scalars(self) -> _ExecuteResult:
            return self

        def all(self) -> list[WorkspaceRuntimeActivitySegment]:
            return [model]

    class _FakeSession:
        async def execute(self, _query: object) -> _ExecuteResult:
            return _ExecuteResult()

    class _FakeSessionContext:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "src.runtime.workspace_runtime_projection.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(),
    )

    repository = SqlAlchemyWorkspaceRuntimeProjectionRepository()
    records = await repository.fetch_activity_segments(
        thread_id="thread-1",
        agent_id="fundamental_analysis",
        limit=5,
        before_updated_at=datetime(2026, 3, 22, 12, 0),
    )

    assert len(records) == 1
    record = records[0]
    assert record.segment_id == "segment-1"
    assert record.agent_id == "fundamental_analysis"
    assert record.status == "running"
    assert record.updated_at == updated_at


def test_derive_active_agent_id_prefers_running_status() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    records = [
        _record(
            event_id="evt-1",
            seq_id=1,
            agent_id="intent_extraction",
            status="done",
            created_at=now - timedelta(minutes=2),
        ),
        _record(
            event_id="evt-2",
            seq_id=2,
            agent_id="financial_news_research",
            status="running",
            created_at=now - timedelta(minutes=1),
        ),
    ]

    assert derive_active_agent_id(records) == "financial_news_research"


def test_derive_recent_activity_orders_by_timestamp() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    records = [
        _record(
            event_id="evt-1",
            seq_id=1,
            agent_id="intent_extraction",
            status="done",
            created_at=now - timedelta(minutes=3),
        ),
        _record(
            event_id="evt-2",
            seq_id=2,
            agent_id="fundamental_analysis",
            status="done",
            created_at=now - timedelta(minutes=2),
        ),
        _record(
            event_id="evt-3",
            seq_id=3,
            agent_id="technical_analysis",
            status="running",
            created_at=now - timedelta(minutes=1),
        ),
    ]

    recent = derive_recent_activity(records, limit=2)

    assert [entry.event_id for entry in recent] == ["evt-3", "evt-2"]


def test_project_activity_segment_updates_existing_segment() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    running_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-run",
        thread_id="thread-1",
        seq_id=1,
        run_id="run-1",
        agent_id="intent_extraction",
        node="intent_extraction",
        event_type="agent.status",
        status="running",
        payload={},
        created_at=now,
    )
    first_segment = project_activity_segment(
        event=running_event,
        latest_segment=None,
    )
    assert first_segment is not None
    assert first_segment.status == "running"
    assert first_segment.ended_at is None

    done_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-done",
        thread_id="thread-1",
        seq_id=2,
        run_id="run-1",
        agent_id="intent_extraction",
        node="intent_extraction",
        event_type="agent.status",
        status="done",
        payload={},
        created_at=now + timedelta(minutes=1),
    )
    updated_segment = project_activity_segment(
        event=done_event,
        latest_segment=first_segment,
    )
    assert updated_segment is not None
    assert updated_segment.segment_id == first_segment.segment_id
    assert updated_segment.status == "done"
    assert updated_segment.ended_at == done_event.created_at


def test_project_activity_segment_dedupes_terminal_events() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    done_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-done",
        thread_id="thread-1",
        seq_id=1,
        run_id="run-1",
        agent_id="intent_extraction",
        node="clarifying",
        event_type="agent.status",
        status="done",
        payload={},
        created_at=now,
    )
    first_segment = project_activity_segment(
        event=done_event,
        latest_segment=None,
    )
    assert first_segment is not None
    assert first_segment.status == "done"
    assert first_segment.ended_at == done_event.created_at

    duplicate_done = WorkspaceRuntimeActivityRecord(
        event_id="evt-done-2",
        thread_id="thread-1",
        seq_id=2,
        run_id="run-1",
        agent_id="intent_extraction",
        node="clarifying",
        event_type="agent.status",
        status="done",
        payload={},
        created_at=now + timedelta(seconds=10),
    )
    deduped = project_activity_segment(
        event=duplicate_done,
        latest_segment=first_segment,
    )
    assert deduped is None


def test_project_activity_segment_requires_run_id() -> None:
    event = WorkspaceRuntimeActivityRecord(
        event_id="evt-1",
        thread_id="thread-1",
        seq_id=1,
        run_id=None,
        agent_id="intent_extraction",
        node="intent_extraction",
        event_type="agent.status",
        status="running",
        payload={},
        created_at=datetime(2026, 3, 21, 12, 0),
    )
    assert project_activity_segment(event=event, latest_segment=None) is None


def test_project_activity_segment_requires_node() -> None:
    event = WorkspaceRuntimeActivityRecord(
        event_id="evt-1",
        thread_id="thread-1",
        seq_id=1,
        run_id="run-1",
        agent_id="intent_extraction",
        node=None,
        event_type="agent.status",
        status="running",
        payload={},
        created_at=datetime(2026, 3, 21, 12, 0),
    )
    assert project_activity_segment(event=event, latest_segment=None) is None


def test_project_run_status_updates_existing_record() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    running_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-run",
        thread_id="thread-1",
        seq_id=1,
        run_id="run-1",
        agent_id="system",
        node=None,
        event_type="lifecycle.status",
        status="running",
        payload={},
        created_at=now,
    )
    first = project_run_status(event=running_event, latest_status=None)
    assert first is not None
    assert first.status == "running"
    assert first.ended_at is None

    done_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-done",
        thread_id="thread-1",
        seq_id=2,
        run_id="run-1",
        agent_id="system",
        node=None,
        event_type="lifecycle.status",
        status="done",
        payload={},
        created_at=now + timedelta(minutes=1),
    )
    updated = project_run_status(event=done_event, latest_status=first)
    assert updated is not None
    assert updated.run_id == first.run_id
    assert updated.status == "done"
    assert updated.ended_at == done_event.created_at


def test_project_run_status_requires_run_id() -> None:
    event = WorkspaceRuntimeActivityRecord(
        event_id="evt-1",
        thread_id="thread-1",
        seq_id=1,
        run_id=None,
        agent_id="system",
        node=None,
        event_type="lifecycle.status",
        status="running",
        payload={},
        created_at=datetime(2026, 3, 21, 12, 0),
    )
    assert project_run_status(event=event, latest_status=None) is None


def test_project_run_status_handles_interrupt() -> None:
    now = datetime(2026, 3, 21, 12, 0)
    interrupt_event = WorkspaceRuntimeActivityRecord(
        event_id="evt-int",
        thread_id="thread-1",
        seq_id=3,
        run_id="run-2",
        agent_id="intent_extraction",
        node="clarifying",
        event_type="interrupt.request",
        status=None,
        payload={},
        created_at=now,
    )
    projected = project_run_status(event=interrupt_event, latest_status=None)
    assert projected is not None
    assert projected.status == "attention"


def test_chat_message_to_dict_prefers_agent_id_column() -> None:
    message = ChatMessage(
        thread_id="thread-1",
        role="assistant",
        content="hello",
        message_type="ai",
        metadata_={"agentId": "legacy-agent"},
        agent_id="current-agent",
    )

    payload = message.to_dict()

    assert payload["agentId"] == "current-agent"
