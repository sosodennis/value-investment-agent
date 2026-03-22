from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.interface.events.protocol import AgentEvent
from src.runtime.workspace_runtime_projection.application.runtime_projection_service import (
    WorkspaceRuntimeProjectionService,
)
from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeCursorRecord,
    WorkspaceRuntimeRunStatusRecord,
)


class _FakeRepository:
    def __init__(self) -> None:
        self.records: list[WorkspaceRuntimeActivityRecord] = []
        self.segments: list[WorkspaceRuntimeActivitySegmentRecord] = []
        self.cursor: WorkspaceRuntimeCursorRecord | None = None
        self.run_status: WorkspaceRuntimeRunStatusRecord | None = None

    async def append_activity_event(
        self, record: WorkspaceRuntimeActivityRecord
    ) -> None:
        self.records.append(record)

    async def fetch_recent_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> list[WorkspaceRuntimeActivityRecord]:
        return [record for record in self.records if record.thread_id == thread_id][
            :limit
        ]

    async def fetch_latest_activity_segment_by_node(
        self,
        *,
        thread_id: str,
        agent_id: str,
        run_id: str,
        node: str,
    ) -> WorkspaceRuntimeActivitySegmentRecord | None:
        candidates = [
            segment
            for segment in self.segments
            if segment.thread_id == thread_id
            and segment.agent_id == agent_id
            and segment.run_id == run_id
            and segment.node == node
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda segment: segment.last_seq_id)

    async def fetch_activity_segments(
        self,
        *,
        thread_id: str,
        agent_id: str,
        limit: int = 5,
        before_updated_at: datetime | None = None,
    ) -> list[WorkspaceRuntimeActivitySegmentRecord]:
        entries = [
            segment
            for segment in self.segments
            if segment.thread_id == thread_id and segment.agent_id == agent_id
        ]
        if before_updated_at is not None:
            entries = [
                segment for segment in entries if segment.updated_at < before_updated_at
            ]
        ordered = sorted(entries, key=lambda segment: segment.updated_at, reverse=True)
        return ordered[:limit]

    async def fetch_latest_cursor(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeCursorRecord | None:
        if self.cursor and self.cursor.thread_id == thread_id:
            return self.cursor
        return None

    async def fetch_latest_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]:
        return {}

    async def fetch_run_status(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeRunStatusRecord | None:
        if self.run_status and self.run_status.thread_id == thread_id:
            return self.run_status
        return None

    async def upsert_run_status(
        self,
        record: WorkspaceRuntimeRunStatusRecord,
    ) -> None:
        self.run_status = record

    async def append_activity_segment(
        self, record: WorkspaceRuntimeActivitySegmentRecord
    ) -> None:
        self.segments.append(record)

    async def update_activity_segment(
        self, record: WorkspaceRuntimeActivitySegmentRecord
    ) -> None:
        for idx, existing in enumerate(self.segments):
            if existing.segment_id == record.segment_id:
                self.segments[idx] = record
                return
        self.segments.append(record)

    async def close_open_segments_for_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: str,
        closed_at: datetime,
    ) -> None:
        updated: list[WorkspaceRuntimeActivitySegmentRecord] = []
        for segment in self.segments:
            if (
                segment.thread_id == thread_id
                and segment.run_id == run_id
                and segment.ended_at is None
            ):
                updated.append(
                    WorkspaceRuntimeActivitySegmentRecord(
                        segment_id=segment.segment_id,
                        thread_id=segment.thread_id,
                        agent_id=segment.agent_id,
                        node=segment.node,
                        run_id=segment.run_id,
                        status=status,
                        started_at=segment.started_at,
                        updated_at=closed_at,
                        ended_at=closed_at,
                        last_seq_id=segment.last_seq_id,
                    )
                )
            else:
                updated.append(segment)
        self.segments = updated

    async def upsert_cursor(
        self,
        *,
        thread_id: str,
        last_seq_id: int,
    ) -> WorkspaceRuntimeCursorRecord:
        now = datetime(2026, 3, 21, 12, 0)
        if self.cursor is None or self.cursor.thread_id != thread_id:
            self.cursor = WorkspaceRuntimeCursorRecord(
                thread_id=thread_id,
                last_seq_id=last_seq_id,
                updated_at=now,
            )
            return self.cursor
        if last_seq_id > self.cursor.last_seq_id:
            self.cursor = WorkspaceRuntimeCursorRecord(
                thread_id=thread_id,
                last_seq_id=last_seq_id,
                updated_at=now,
            )
        return self.cursor


@pytest.mark.asyncio
async def test_record_event_appends_activity_and_updates_cursor() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=12,
        type="agent.status",
        source="fundamental_analysis",
        data={"status": "running", "node": "fundamental_analysis"},
    )

    await service.record_event(event)

    assert len(repo.records) == 1
    record = repo.records[0]
    assert record.event_id == event.id
    assert record.seq_id == 12
    assert record.agent_id == "fundamental_analysis"
    assert record.event_type == "agent.status"
    assert record.status == "running"
    assert record.node == "fundamental_analysis"
    assert len(repo.segments) == 1
    segment = repo.segments[0]
    assert segment.agent_id == "fundamental_analysis"
    assert segment.run_id == "run-1"
    assert segment.status == "running"
    assert repo.cursor is not None
    assert repo.cursor.last_seq_id == 12


@pytest.mark.asyncio
async def test_record_event_updates_run_status_for_lifecycle() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=20,
        type="lifecycle.status",
        source="System",
        data={"status": "running"},
    )

    await service.record_event(event)

    assert repo.run_status is not None
    assert repo.run_status.status == "running"
    assert repo.run_status.run_id == "run-1"


@pytest.mark.asyncio
async def test_record_event_closes_open_segments_on_run_end() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    started_at = datetime(2026, 3, 21, 12, 0)
    running_event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=10,
        timestamp=started_at,
        type="agent.status",
        source="intent_extraction",
        data={"status": "running", "node": "clarifying"},
    )
    await service.record_event(running_event)
    assert len(repo.segments) == 1
    assert repo.segments[0].ended_at is None

    ended_at = started_at.replace() + timedelta(minutes=1)
    done_event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=11,
        timestamp=ended_at,
        type="lifecycle.status",
        source="System",
        data={"status": "done"},
    )
    await service.record_event(done_event)

    assert len(repo.segments) == 1
    segment = repo.segments[0]
    assert segment.status == "done"
    assert segment.ended_at == ended_at


@pytest.mark.asyncio
async def test_record_event_updates_run_status_for_interrupt() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=21,
        type="interrupt.request",
        source="intent_extraction",
        data={"type": "ticker_selection", "candidates": []},
    )

    await service.record_event(event)

    assert repo.run_status is not None
    assert repo.run_status.status == "attention"


@pytest.mark.asyncio
async def test_record_event_updates_run_status_for_error() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=22,
        type="error",
        source="System",
        data={"message": "boom"},
    )

    await service.record_event(event)

    assert repo.run_status is not None
    assert repo.run_status.status == "error"


@pytest.mark.asyncio
async def test_record_event_updates_cursor_for_content_delta() -> None:
    repo = _FakeRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=7,
        type="content.delta",
        source="fundamental_analysis",
        data={"content": "hello"},
    )

    await service.record_event(event)

    assert repo.records == []
    assert repo.cursor is not None
    assert repo.cursor.last_seq_id == 7


@pytest.mark.asyncio
async def test_resolve_next_seq_id_prefers_cursor() -> None:
    repo = _FakeRepository()
    repo.cursor = WorkspaceRuntimeCursorRecord(
        thread_id="thread-1",
        last_seq_id=40,
        updated_at=datetime(2026, 3, 21, 12, 0),
    )
    service = WorkspaceRuntimeProjectionService(repository=repo)

    next_seq = await service.resolve_next_seq_id(
        thread_id="thread-1", fallback_seq_id=1
    )

    assert next_seq == 41


@pytest.mark.asyncio
async def test_record_event_ignores_duplicate_seq_id() -> None:
    class _FailingRepository(_FakeRepository):
        async def append_activity_event(
            self, record: WorkspaceRuntimeActivityRecord
        ) -> None:
            raise IntegrityError("stmt", "params", Exception("duplicate"))

    repo = _FailingRepository()
    service = WorkspaceRuntimeProjectionService(repository=repo)
    event = AgentEvent(
        thread_id="thread-1",
        run_id="run-1",
        seq_id=9,
        type="agent.status",
        source="technical_analysis",
        data={"status": "running", "node": "technical_analysis"},
    )

    await service.record_event(event)

    assert repo.cursor is not None
    assert repo.cursor.last_seq_id == 9
