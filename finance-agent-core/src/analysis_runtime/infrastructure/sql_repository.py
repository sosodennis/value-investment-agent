from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivitySnapshot,
    AnalysisRunPage,
    AnalysisRunRecord,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    InvalidCursorError,
    ReplayGapError,
)
from src.auth.infrastructure.models import OwnedResourceModel
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    WorkflowActivityCursor,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
)


@dataclass(frozen=True)
class SqlAlchemyActivityRepository:
    async def append_atomic(self, event: ActivityEvent) -> bool:
        async with AsyncSessionLocal() as session:
            try:
                cursor = await session.get(
                    WorkflowActivityCursor, event.thread_id, with_for_update=True
                )
                latest = cursor.last_seq_id if cursor else 0
                if event.seq_id <= latest:
                    duplicate = await session.scalar(
                        select(WorkflowActivityEvent.event_id).where(
                            WorkflowActivityEvent.event_id == event.event_id
                        )
                    )
                    if duplicate:
                        return False
                    raise ActivityPersistenceError("event sequence is not append-only")
                if event.seq_id != latest + 1:
                    raise ActivityPersistenceError("event sequence contains a gap")
                session.add(
                    WorkflowActivityEvent(
                        event_id=event.event_id,
                        thread_id=event.thread_id,
                        run_id=event.run_id,
                        seq_id=event.seq_id,
                        event_version=event.event_version,
                        event_name=event.event_name,
                        occurred_at=event.occurred_at.replace(tzinfo=None),
                        payload=event.payload.model_dump(mode="json"),
                    )
                )
                if cursor is None:
                    session.add(
                        WorkflowActivityCursor(
                            thread_id=event.thread_id,
                            last_seq_id=event.seq_id,
                            updated_at=event.occurred_at.replace(tzinfo=None),
                        )
                    )
                else:
                    cursor.last_seq_id = event.seq_id
                    cursor.updated_at = event.occurred_at.replace(tzinfo=None)
                await session.commit()
                return True
            except ActivityPersistenceError:
                await session.rollback()
                raise
            except Exception as exc:
                await session.rollback()
                raise ActivityPersistenceError(
                    "activity event persistence failed"
                ) from exc

    async def replay(self, *, thread_id: str, after_seq: int, limit: int) -> ReplayPage:
        if after_seq < 0 or limit < 1:
            raise InvalidCursorError("invalid replay cursor or limit")
        async with AsyncSessionLocal() as session:
            oldest = await session.scalar(
                select(func.min(WorkflowActivityEvent.seq_id)).where(
                    WorkflowActivityEvent.thread_id == thread_id
                )
            )
            if oldest is not None and after_seq < oldest - 1:
                raise ReplayGapError(oldest, after_seq)
            rows = (
                await session.scalars(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == thread_id)
                    .where(WorkflowActivityEvent.seq_id > after_seq)
                    .order_by(WorkflowActivityEvent.seq_id.asc())
                    .limit(limit + 1)
                )
            ).all()
        events = tuple(self._to_event(row) for row in rows[:limit])
        return ReplayPage(
            events=events,
            cursor=events[-1].seq_id if events else after_seq,
            has_more=len(rows) > limit,
        )

    async def snapshot(self, *, thread_id: str, run_id: str) -> ActivitySnapshot:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.scalars(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == thread_id)
                    .where(WorkflowActivityEvent.run_id == run_id)
                    .order_by(WorkflowActivityEvent.seq_id.asc())
                )
            ).all()
            history = await session.get(WorkflowRunHistory, (thread_id, run_id))
            cursor_row = await session.get(WorkflowActivityCursor, thread_id)
        events = tuple(self._to_event(row) for row in rows)
        latest: dict[str, ActivityEvent] = {}
        for event in events:
            latest[event.payload.activity_id] = event
        active = tuple(
            event.payload
            for event in latest.values()
            if event.payload.status in {"queued", "running", "waiting"}
        )
        return ActivitySnapshot(
            thread_id=thread_id,
            run_id=run_id,
            run_status=history.status if history else "queued",
            cursor=cursor_row.last_seq_id if cursor_row else 0,
            active_activities=active,
            recent_activities=tuple(event.payload for event in reversed(events))[:50],
        )

    async def get_run_history(
        self, *, principal_id: str, thread_id: str, run_id: str
    ) -> AnalysisRunRecord | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(WorkflowRunHistory, (thread_id, run_id))
        if row is None or row.principal_id != principal_id:
            return None
        return self._history_from_model(row)

    async def list_run_history(
        self,
        *,
        principal_id: str,
        limit: int,
        before_started_at: datetime | None = None,
        before_thread_id: str | None = None,
        before_run_id: str | None = None,
    ) -> AnalysisRunPage:
        if limit < 1 or limit > 100:
            raise InvalidCursorError("run history limit must be between 1 and 100")
        if (before_thread_id is None) != (before_run_id is None) or (
            before_started_at is not None
            and (before_thread_id is None or before_run_id is None)
        ):
            raise InvalidCursorError("run history cursor is incomplete")
        async with AsyncSessionLocal() as session:
            query = select(WorkflowRunHistory).where(
                WorkflowRunHistory.principal_id == principal_id
            )
            if before_thread_id is not None and before_run_id is not None:
                if before_started_at is None:
                    query = query.where(
                        WorkflowRunHistory.started_at.is_(None),
                        or_(
                            WorkflowRunHistory.thread_id < before_thread_id,
                            and_(
                                WorkflowRunHistory.thread_id == before_thread_id,
                                WorkflowRunHistory.run_id < before_run_id,
                            ),
                        ),
                    )
                else:
                    before = before_started_at.replace(tzinfo=None)
                    query = query.where(
                        or_(
                            WorkflowRunHistory.started_at.is_(None),
                            WorkflowRunHistory.started_at < before,
                            and_(
                                WorkflowRunHistory.started_at == before,
                                WorkflowRunHistory.thread_id < before_thread_id,
                            ),
                            and_(
                                WorkflowRunHistory.started_at == before,
                                WorkflowRunHistory.thread_id == before_thread_id,
                                WorkflowRunHistory.run_id < before_run_id,
                            ),
                        )
                    )
            rows = (
                await session.scalars(
                    query.order_by(
                        WorkflowRunHistory.started_at.desc().nullslast(),
                        WorkflowRunHistory.thread_id.desc(),
                        WorkflowRunHistory.run_id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        records = tuple(self._history_from_model(row) for row in selected)
        last = records[-1] if records else None
        return AnalysisRunPage(
            runs=records,
            has_more=has_more,
            next_started_at=last.started_at if has_more and last else None,
            next_thread_id=last.thread_id if has_more and last else None,
            next_run_id=last.run_id if has_more and last else None,
        )

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(WorkflowRun, thread_id)
        return self._run_from_model(row) if row else None

    async def set_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: RunStatus,
        now: datetime,
        principal_id: str | None = None,
        input_data: Mapping[str, object] | None = None,
    ) -> RunStatusRecord:
        async with AsyncSessionLocal() as session:
            row = await session.get(WorkflowRun, thread_id)
            started = (
                row.started_at
                if row and row.run_id == run_id
                else now.replace(tzinfo=None)
            )
            if row is None:
                row = WorkflowRun(
                    thread_id=thread_id, run_id=run_id, started_at=started
                )
                session.add(row)
            row.run_id = run_id
            row.status = status
            row.started_at = started
            row.updated_at = now.replace(tzinfo=None)
            row.ended_at = (
                now.replace(tzinfo=None)
                if status in {"completed", "failed", "cancelled"}
                else None
            )
            history = await session.get(
                WorkflowRunHistory, (thread_id, run_id), with_for_update=True
            )
            if history is None:
                if principal_id is None:
                    owner = await session.scalar(
                        select(OwnedResourceModel.user_id)
                        .where(OwnedResourceModel.resource_type == "thread")
                        .where(OwnedResourceModel.resource_id == thread_id)
                    )
                    principal_id = owner
                if principal_id is not None:
                    history = WorkflowRunHistory(
                        thread_id=thread_id,
                        run_id=run_id,
                        principal_id=principal_id,
                        status=status,
                        started_at=started,
                        input_data=dict(input_data) if input_data is not None else None,
                    )
                    session.add(history)
            if history is not None:
                if principal_id is not None and history.principal_id != principal_id:
                    raise ActivityPersistenceError("run owner cannot change")
                history.status = status
                history.updated_at = now.replace(tzinfo=None)
                history.ended_at = row.ended_at
                if input_data is not None and history.input_data is None:
                    history.input_data = dict(input_data)
            await session.commit()
            return RunStatusRecord(
                thread_id=thread_id,
                run_id=run_id,
                status=status,
                started_at=started.replace(tzinfo=timezone.utc),
                updated_at=now,
                ended_at=now if row.ended_at else None,
            )

    @staticmethod
    def _to_event(row: WorkflowActivityEvent) -> ActivityEvent:
        payload = Activity.model_validate(row.payload)
        return ActivityEvent(
            event_id=row.event_id,
            seq_id=row.seq_id,
            event_version=row.event_version,
            event_name=row.event_name,
            thread_id=row.thread_id,
            run_id=row.run_id,
            occurred_at=row.occurred_at.replace(tzinfo=timezone.utc),
            payload=payload,
        )

    @staticmethod
    def _run_from_model(row: WorkflowRun) -> RunStatusRecord:
        return RunStatusRecord(
            thread_id=row.thread_id,
            run_id=row.run_id,
            status=row.status,
            started_at=row.started_at.replace(tzinfo=timezone.utc),
            updated_at=row.updated_at.replace(tzinfo=timezone.utc),
            ended_at=row.ended_at.replace(tzinfo=timezone.utc)
            if row.ended_at
            else None,
        )

    @staticmethod
    def _history_from_model(row: WorkflowRunHistory) -> AnalysisRunRecord:
        return AnalysisRunRecord(
            thread_id=row.thread_id,
            run_id=row.run_id,
            status=row.status,
            started_at=row.started_at.replace(tzinfo=timezone.utc)
            if row.started_at
            else None,
            updated_at=row.updated_at.replace(tzinfo=timezone.utc)
            if row.updated_at
            else None,
            ended_at=row.ended_at.replace(tzinfo=timezone.utc)
            if row.ended_at
            else None,
            input_data=row.input_data,
        )
