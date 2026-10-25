from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivitySnapshot,
    PendingResume,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
    TickerSelectionResponse,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    InteractionNotAvailableError,
    InvalidCursorError,
    InvalidInteractionResponseError,
    ReplayGapError,
)
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    WorkflowActivityCursor,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunResume,
)


@dataclass(frozen=True)
class SqlAlchemyActivityRepository:
    async def append_atomic(
        self, event: ActivityEvent, *, run_status: RunStatus | None = None
    ) -> bool:
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
                run = None
                if run_status is not None:
                    run = await session.scalar(
                        select(WorkflowRun)
                        .where(WorkflowRun.thread_id == event.thread_id)
                        .with_for_update()
                    )
                    if run is None or run.run_id != event.run_id:
                        raise ActivityPersistenceError(
                            "run status does not match activity event"
                        )
                    run.status = run_status
                    run.updated_at = event.occurred_at.replace(tzinfo=None)
                    run.ended_at = (
                        event.occurred_at.replace(tzinfo=None)
                        if run_status in {"completed", "failed", "cancelled"}
                        else None
                    )
                    if run_status in {"waiting", "completed", "failed", "cancelled"}:
                        pending_resume = await session.get(
                            WorkflowRunResume, event.thread_id, with_for_update=True
                        )
                        if pending_resume is not None:
                            await session.delete(pending_resume)
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
        replay = await self.replay(thread_id=thread_id, after_seq=0, limit=100_000)
        latest: dict[str, ActivityEvent] = {}
        for event in replay.events:
            if event.run_id == run_id:
                latest[event.payload.activity_id] = event
        active = tuple(
            event.payload
            for event in latest.values()
            if event.payload.status in {"queued", "running", "waiting"}
        )
        run = await self.get_run(thread_id=thread_id)
        return ActivitySnapshot(
            thread_id=thread_id,
            run_id=run_id,
            run_status=run.status if run else "queued",
            cursor=replay.cursor,
            active_activities=active,
            recent_activities=tuple(
                event.payload
                for event in reversed(replay.events)
                if event.run_id == run_id
            )[:50],
        )

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(WorkflowRun, thread_id)
        return self._run_from_model(row) if row else None

    async def set_run(
        self, *, thread_id: str, run_id: str, status: RunStatus, now: datetime
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
            if status in {"completed", "failed", "cancelled"}:
                pending_resume = await session.get(
                    WorkflowRunResume, thread_id, with_for_update=True
                )
                if pending_resume is not None:
                    await session.delete(pending_resume)
            await session.commit()
            return RunStatusRecord(
                thread_id=thread_id,
                run_id=run_id,
                status=status,
                started_at=started.replace(tzinfo=timezone.utc),
                updated_at=now,
                ended_at=now if row.ended_at else None,
            )

    async def claim_resume(
        self,
        *,
        thread_id: str,
        run_id: str,
        activity_id: str,
        interaction_id: str,
        response: TickerSelectionResponse,
        principal_id: str,
        now: datetime,
    ) -> Activity:
        async with AsyncSessionLocal() as session:
            run = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == thread_id)
                .with_for_update()
            )
            if run is None or run.run_id != run_id:
                raise InteractionNotAvailableError("run cannot accept this interaction")
            if run.status != "waiting":
                raise InteractionNotAvailableError("run is not waiting for input")

            row = await session.scalar(
                select(WorkflowActivityEvent)
                .where(WorkflowActivityEvent.thread_id == thread_id)
                .where(WorkflowActivityEvent.run_id == run_id)
                .where(
                    WorkflowActivityEvent.payload["activity_id"].as_string()
                    == activity_id
                )
                .order_by(WorkflowActivityEvent.seq_id.desc())
                .limit(1)
                .with_for_update()
            )
            activity = Activity.model_validate(row.payload) if row is not None else None
            if (
                activity is None
                or activity.status != "waiting"
                or activity.interruption is None
                or activity.interruption.interaction_id != interaction_id
            ):
                raise InteractionNotAvailableError(
                    "interaction is stale or unavailable"
                )
            if response.selected_symbol not in {
                item.symbol for item in activity.interruption.request.candidates
            }:
                raise InvalidInteractionResponseError(
                    "selected symbol is not one of the available candidates"
                )

            run.status = "running"
            run.updated_at = now.replace(tzinfo=None)
            run.ended_at = None
            session.add(
                WorkflowRunResume(
                    thread_id=thread_id,
                    run_id=run_id,
                    principal_id=principal_id,
                    activity_id=activity_id,
                    interaction_id=interaction_id,
                    response=response.model_dump(mode="json"),
                    created_at=now.replace(tzinfo=None),
                )
            )
            await session.commit()
            return activity

    async def pending_resumes(self) -> tuple[PendingResume, ...]:
        async with AsyncSessionLocal() as session:
            pending_rows = (await session.scalars(select(WorkflowRunResume))).all()
            pending: list[PendingResume] = []
            for row in pending_rows:
                run = await session.get(WorkflowRun, row.thread_id)
                if run is None or run.run_id != row.run_id or run.status != "running":
                    continue
                event_row = await session.scalar(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == row.thread_id)
                    .where(WorkflowActivityEvent.run_id == row.run_id)
                    .where(
                        WorkflowActivityEvent.payload["activity_id"].as_string()
                        == row.activity_id
                    )
                    .order_by(WorkflowActivityEvent.seq_id.desc())
                    .limit(1)
                )
                activity = (
                    Activity.model_validate(event_row.payload)
                    if event_row is not None
                    else None
                )
                if (
                    activity is None
                    or activity.interruption is None
                    or activity.interruption.interaction_id != row.interaction_id
                ):
                    continue
                pending.append(
                    PendingResume(
                        thread_id=row.thread_id,
                        run_id=row.run_id,
                        principal_id=row.principal_id,
                        activity=activity.interruption,
                        activity_id=activity.activity_id,
                        scope_path=activity.scope_path,
                        attempt=activity.attempt,
                        response=TickerSelectionResponse.model_validate(row.response),
                    )
                )
            return tuple(pending)

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
