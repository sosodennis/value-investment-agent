from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    WorkspaceRuntimeActivityEvent,
    WorkspaceRuntimeActivitySegment,
    WorkspaceRuntimeCursor,
    WorkspaceRuntimeRunStatus,
)
from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeCursorRecord,
    WorkspaceRuntimeRunStatusRecord,
)


@dataclass(frozen=True)
class SqlAlchemyWorkspaceRuntimeProjectionRepository:
    async def append_activity_event(
        self,
        record: WorkspaceRuntimeActivityRecord,
    ) -> None:
        async with AsyncSessionLocal() as session:
            model = WorkspaceRuntimeActivityEvent(
                event_id=record.event_id,
                thread_id=record.thread_id,
                seq_id=record.seq_id,
                run_id=record.run_id,
                agent_id=record.agent_id,
                node=record.node,
                event_type=record.event_type,
                status=record.status,
                payload=record.payload,
                created_at=record.created_at,
            )
            session.add(model)
            await session.commit()

    async def fetch_recent_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> list[WorkspaceRuntimeActivityRecord]:
        async with AsyncSessionLocal() as session:
            query = (
                select(WorkspaceRuntimeActivityEvent)
                .where(WorkspaceRuntimeActivityEvent.thread_id == thread_id)
                .order_by(WorkspaceRuntimeActivityEvent.seq_id.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            rows = list(result.scalars().all())
        return [self._activity_record_from_model(row) for row in rows]

    async def fetch_activity_since(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int = 200,
    ) -> list[WorkspaceRuntimeActivityRecord]:
        async with AsyncSessionLocal() as session:
            query = (
                select(WorkspaceRuntimeActivityEvent)
                .where(WorkspaceRuntimeActivityEvent.thread_id == thread_id)
                .where(WorkspaceRuntimeActivityEvent.seq_id > after_seq)
                .order_by(WorkspaceRuntimeActivityEvent.seq_id.asc())
                .limit(limit)
            )
            result = await session.execute(query)
            rows = list(result.scalars().all())
        return [self._activity_record_from_model(row) for row in rows]

    async def fetch_latest_activity_segment_by_node(
        self,
        *,
        thread_id: str,
        agent_id: str,
        run_id: str,
        node: str,
    ) -> WorkspaceRuntimeActivitySegmentRecord | None:
        async with AsyncSessionLocal() as session:
            query = (
                select(WorkspaceRuntimeActivitySegment)
                .where(WorkspaceRuntimeActivitySegment.thread_id == thread_id)
                .where(WorkspaceRuntimeActivitySegment.agent_id == agent_id)
                .where(WorkspaceRuntimeActivitySegment.run_id == run_id)
                .where(WorkspaceRuntimeActivitySegment.node == node)
                .order_by(WorkspaceRuntimeActivitySegment.last_seq_id.desc())
                .limit(1)
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._activity_segment_record_from_model(row)

    async def fetch_activity_segments(
        self,
        *,
        thread_id: str,
        agent_id: str,
        limit: int = 5,
        before_updated_at: datetime | None = None,
    ) -> list[WorkspaceRuntimeActivitySegmentRecord]:
        async with AsyncSessionLocal() as session:
            query = (
                select(WorkspaceRuntimeActivitySegment)
                .where(WorkspaceRuntimeActivitySegment.thread_id == thread_id)
                .where(WorkspaceRuntimeActivitySegment.agent_id == agent_id)
                .order_by(
                    WorkspaceRuntimeActivitySegment.updated_at.desc(),
                    WorkspaceRuntimeActivitySegment.last_seq_id.desc(),
                )
                .limit(limit)
            )
            if before_updated_at is not None:
                query = query.where(
                    WorkspaceRuntimeActivitySegment.updated_at < before_updated_at
                )
            result = await session.execute(query)
            rows = list(result.scalars().all())
        return [self._activity_segment_record_from_model(row) for row in rows]

    async def fetch_latest_cursor(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeCursorRecord | None:
        async with AsyncSessionLocal() as session:
            query = select(WorkspaceRuntimeCursor).where(
                WorkspaceRuntimeCursor.thread_id == thread_id
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._cursor_record_from_model(row)

    async def fetch_latest_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]:
        async with AsyncSessionLocal() as session:
            subquery = (
                select(
                    WorkspaceRuntimeActivityEvent.agent_id.label("agent_id"),
                    func.max(WorkspaceRuntimeActivityEvent.seq_id).label("max_seq"),
                )
                .where(WorkspaceRuntimeActivityEvent.thread_id == thread_id)
                .where(WorkspaceRuntimeActivityEvent.event_type == "agent.status")
                .where(WorkspaceRuntimeActivityEvent.status.isnot(None))
                .group_by(WorkspaceRuntimeActivityEvent.agent_id)
                .subquery()
            )
            query = select(
                WorkspaceRuntimeActivityEvent.agent_id,
                WorkspaceRuntimeActivityEvent.status,
            ).join(
                subquery,
                (WorkspaceRuntimeActivityEvent.agent_id == subquery.c.agent_id)
                & (WorkspaceRuntimeActivityEvent.seq_id == subquery.c.max_seq),
            )
            result = await session.execute(query)
            rows = result.all()
        return {agent_id: status for agent_id, status in rows if status}

    async def fetch_latest_lifecycle_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]:
        async with AsyncSessionLocal() as session:
            subquery = (
                select(
                    WorkspaceRuntimeActivityEvent.agent_id.label("agent_id"),
                    func.max(WorkspaceRuntimeActivityEvent.seq_id).label("max_seq"),
                )
                .where(WorkspaceRuntimeActivityEvent.thread_id == thread_id)
                .where(WorkspaceRuntimeActivityEvent.event_type == "agent.lifecycle")
                .where(WorkspaceRuntimeActivityEvent.status.isnot(None))
                .group_by(WorkspaceRuntimeActivityEvent.agent_id)
                .subquery()
            )
            query = select(
                WorkspaceRuntimeActivityEvent.agent_id,
                WorkspaceRuntimeActivityEvent.status,
            ).join(
                subquery,
                (WorkspaceRuntimeActivityEvent.agent_id == subquery.c.agent_id)
                & (WorkspaceRuntimeActivityEvent.seq_id == subquery.c.max_seq),
            )
            result = await session.execute(query)
            rows = result.all()
        return {agent_id: status for agent_id, status in rows if status}

    async def fetch_run_status(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeRunStatusRecord | None:
        async with AsyncSessionLocal() as session:
            query = select(WorkspaceRuntimeRunStatus).where(
                WorkspaceRuntimeRunStatus.thread_id == thread_id
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._run_status_record_from_model(row)

    async def upsert_run_status(
        self,
        record: WorkspaceRuntimeRunStatusRecord,
    ) -> None:
        async with AsyncSessionLocal() as session:
            query = select(WorkspaceRuntimeRunStatus).where(
                WorkspaceRuntimeRunStatus.thread_id == record.thread_id
            )
            result = await session.execute(query)
            existing = result.scalar_one_or_none()
            if existing is None:
                model = WorkspaceRuntimeRunStatus(
                    thread_id=record.thread_id,
                    run_id=record.run_id,
                    status=record.status,
                    started_at=record.started_at,
                    updated_at=record.updated_at,
                    ended_at=record.ended_at,
                    last_seq_id=record.last_seq_id,
                )
                session.add(model)
                await session.commit()
                return

            existing.status = record.status
            existing.updated_at = record.updated_at
            existing.ended_at = record.ended_at
            existing.last_seq_id = record.last_seq_id
            await session.commit()

    async def append_activity_segment(
        self,
        record: WorkspaceRuntimeActivitySegmentRecord,
    ) -> None:
        async with AsyncSessionLocal() as session:
            model = WorkspaceRuntimeActivitySegment(
                segment_id=record.segment_id,
                thread_id=record.thread_id,
                agent_id=record.agent_id,
                node=record.node,
                run_id=record.run_id,
                status=record.status,
                started_at=record.started_at,
                updated_at=record.updated_at,
                ended_at=record.ended_at,
                last_seq_id=record.last_seq_id,
            )
            session.add(model)
            await session.commit()

    async def update_activity_segment(
        self,
        record: WorkspaceRuntimeActivitySegmentRecord,
    ) -> None:
        async with AsyncSessionLocal() as session:
            query = select(WorkspaceRuntimeActivitySegment).where(
                WorkspaceRuntimeActivitySegment.segment_id == record.segment_id
            )
            result = await session.execute(query)
            existing = result.scalar_one_or_none()
            if existing is None:
                model = WorkspaceRuntimeActivitySegment(
                    segment_id=record.segment_id,
                    thread_id=record.thread_id,
                    agent_id=record.agent_id,
                    node=record.node,
                    run_id=record.run_id,
                    status=record.status,
                    started_at=record.started_at,
                    updated_at=record.updated_at,
                    ended_at=record.ended_at,
                    last_seq_id=record.last_seq_id,
                )
                session.add(model)
                await session.commit()
                return

            existing.status = record.status
            existing.updated_at = record.updated_at
            existing.ended_at = record.ended_at
            existing.last_seq_id = record.last_seq_id
            await session.commit()

    async def close_open_segments_for_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: str,
        closed_at: datetime,
    ) -> None:
        async with AsyncSessionLocal() as session:
            query = (
                update(WorkspaceRuntimeActivitySegment)
                .where(WorkspaceRuntimeActivitySegment.thread_id == thread_id)
                .where(WorkspaceRuntimeActivitySegment.run_id == run_id)
                .where(WorkspaceRuntimeActivitySegment.ended_at.is_(None))
                .values(
                    status=status,
                    updated_at=closed_at,
                    ended_at=closed_at,
                )
            )
            await session.execute(query)
            await session.commit()

    async def upsert_cursor(
        self,
        *,
        thread_id: str,
        last_seq_id: int,
    ) -> WorkspaceRuntimeCursorRecord:
        async with AsyncSessionLocal() as session:
            query = select(WorkspaceRuntimeCursor).where(
                WorkspaceRuntimeCursor.thread_id == thread_id
            )
            result = await session.execute(query)
            existing = result.scalar_one_or_none()
            now = datetime.utcnow()
            if existing is None:
                model = WorkspaceRuntimeCursor(
                    thread_id=thread_id,
                    last_seq_id=last_seq_id,
                    updated_at=now,
                )
                session.add(model)
                await session.commit()
                return self._cursor_record_from_model(model)

            if last_seq_id > existing.last_seq_id:
                existing.last_seq_id = last_seq_id
                existing.updated_at = now
                await session.commit()
            return self._cursor_record_from_model(existing)

    @staticmethod
    def _activity_record_from_model(
        model: WorkspaceRuntimeActivityEvent,
    ) -> WorkspaceRuntimeActivityRecord:
        return WorkspaceRuntimeActivityRecord(
            event_id=model.event_id,
            thread_id=model.thread_id,
            seq_id=model.seq_id,
            run_id=model.run_id,
            agent_id=model.agent_id,
            node=model.node,
            event_type=model.event_type,
            status=model.status,
            payload=model.payload,
            created_at=model.created_at,
        )

    @staticmethod
    def _cursor_record_from_model(
        model: WorkspaceRuntimeCursor,
    ) -> WorkspaceRuntimeCursorRecord:
        return WorkspaceRuntimeCursorRecord(
            thread_id=model.thread_id,
            last_seq_id=model.last_seq_id,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _activity_segment_record_from_model(
        model: WorkspaceRuntimeActivitySegment,
    ) -> WorkspaceRuntimeActivitySegmentRecord:
        return WorkspaceRuntimeActivitySegmentRecord(
            segment_id=model.segment_id,
            thread_id=model.thread_id,
            agent_id=model.agent_id,
            node=model.node,
            run_id=model.run_id,
            status=model.status,
            started_at=model.started_at,
            updated_at=model.updated_at,
            ended_at=model.ended_at,
            last_seq_id=model.last_seq_id,
        )

    @staticmethod
    def _run_status_record_from_model(
        model: WorkspaceRuntimeRunStatus,
    ) -> WorkspaceRuntimeRunStatusRecord:
        return WorkspaceRuntimeRunStatusRecord(
            thread_id=model.thread_id,
            run_id=model.run_id,
            status=model.status,
            started_at=model.started_at,
            updated_at=model.updated_at,
            ended_at=model.ended_at,
            last_seq_id=model.last_seq_id,
        )


def build_default_workspace_runtime_projection_repository() -> (
    SqlAlchemyWorkspaceRuntimeProjectionRepository
):
    return SqlAlchemyWorkspaceRuntimeProjectionRepository()


__all__ = [
    "SqlAlchemyWorkspaceRuntimeProjectionRepository",
    "build_default_workspace_runtime_projection_repository",
]
