from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    AnalysisRunPage,
    AnalysisRunRecord,
    CheckpointIdentity,
    ClaimedInteractionResume,
    InteractionIdentity,
    InteractionRequested,
    InteractionResponse,
    PendingResume,
    ReplayPage,
    RetryOperation,
    RetryOperationView,
    RunStatus,
    RunStatusRecord,
    TickerSelectionRequest,
    TickerSelectionResponse,
    WorkflowAgentOutput,
    WorkflowAgentOutputEvent,
    WorkflowEvent,
    WorkflowInteraction,
    WorkflowInteractionEvent,
    WorkflowSnapshot,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    InteractionNotAvailableError,
    InvalidCheckpointError,
    InvalidCursorError,
    InvalidInteractionResponseError,
    InvalidRetryTransitionError,
    ReplayGapError,
    RetryAlreadyActiveError,
    RetryIdempotencyConflictError,
    RetryNotAvailableError,
)
from src.auth.infrastructure.models import OwnedResourceModel
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    WorkflowActivityCursor,
    WorkflowActivityEvent,
    WorkflowRetryOperation,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunResume,
)

_EVENT_ADAPTER = TypeAdapter(WorkflowEvent)


@dataclass(frozen=True)
class SqlAlchemyActivityRepository:
    async def append_atomic(
        self, event: WorkflowEvent, *, run_status: RunStatus | None = None
    ) -> bool:
        async with AsyncSessionLocal() as session:
            try:
                run = await session.scalar(
                    select(WorkflowRun)
                    .where(WorkflowRun.thread_id == event.thread_id)
                    .with_for_update()
                )
                if run is None or run.run_id != event.run_id:
                    raise ActivityPersistenceError(
                        "event run does not match the active workflow run"
                    )
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
                if run_status is not None:
                    run.status = run_status
                    run.updated_at = event.occurred_at.replace(tzinfo=None)
                    run.ended_at = (
                        event.occurred_at.replace(tzinfo=None)
                        if run_status in {"completed", "failed", "cancelled"}
                        else None
                    )
                    history = await session.get(
                        WorkflowRunHistory,
                        (event.thread_id, event.run_id),
                        with_for_update=True,
                    )
                    if history is not None:
                        history.status = run_status
                        history.updated_at = event.occurred_at.replace(tzinfo=None)
                        history.ended_at = run.ended_at
                if (
                    isinstance(event, ActivityEvent)
                    and event.payload.activity_id != "workflow"
                ):
                    pending_resume = await session.get(
                        WorkflowRunResume, event.thread_id, with_for_update=True
                    )
                    if (
                        pending_resume is not None
                        and pending_resume.run_id == event.run_id
                    ):
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

    async def snapshot(self, *, thread_id: str, run_id: str) -> WorkflowSnapshot:
        async with AsyncSessionLocal() as session:
            await session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
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
            retry_row = await session.scalar(
                select(WorkflowRetryOperation)
                .where(WorkflowRetryOperation.thread_id == thread_id)
                .where(
                    or_(
                        WorkflowRetryOperation.source_run_id == run_id,
                        WorkflowRetryOperation.target_run_id == run_id,
                    )
                )
                .order_by(WorkflowRetryOperation.created_at.desc())
                .limit(1)
            )
        events = tuple(self._to_event(row) for row in rows)
        latest: dict[str, ActivityEvent] = {}
        interactions: dict[str, WorkflowInteraction] = {}
        outputs: dict[str, WorkflowAgentOutput] = {}
        failure = None
        for event in events:
            match event:
                case ActivityEvent():
                    latest[event.payload.activity_id] = event
                    if (
                        event.payload.activity_id == "workflow"
                        and event.payload.failure is not None
                    ):
                        failure = event.payload.failure
                case WorkflowInteractionEvent():
                    interactions[event.payload.identity.interaction_id] = event.payload
                case WorkflowAgentOutputEvent():
                    outputs[
                        f"{event.payload.identity.activity_id}:{event.payload.agent_id}"
                    ] = event.payload
        status = history.status if history else "queued"
        active_statuses = {"queued", "running", "waiting"}
        active = tuple(
            event.payload
            for event in latest.values()
            if status in active_statuses and event.payload.status in active_statuses
        )
        terminal_status = {
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(status)
        return WorkflowSnapshot(
            thread_id=thread_id,
            run_id=run_id,
            run_status=status,
            cursor=cursor_row.last_seq_id if cursor_row else 0,
            active_activities=active,
            recent_activities=tuple(
                event.payload.model_copy(update={"status": terminal_status})
                if terminal_status and event.payload.status in active_statuses
                else event.payload
                for event in reversed(events)
                if isinstance(event, ActivityEvent)
            )[:50],
            pending_interactions=tuple(
                interaction
                for interaction in interactions.values()
                if interaction.status == "pending"
            ),
            completed_outputs=tuple(outputs.values()),
            failure=failure,
            retry_operation=(
                RetryOperationView.from_operation(self._retry_from_model(retry_row))
                if retry_row
                else None
            ),
        )

    async def get_run_history(
        self,
        *,
        principal_id: str,
        organization_id: str = "unscoped",
        thread_id: str,
        run_id: str,
    ) -> AnalysisRunRecord | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(WorkflowRunHistory, (thread_id, run_id))
        if (
            row is None
            or row.principal_id != principal_id
            or row.organization_id != organization_id
        ):
            return None
        return self._history_from_model(row)

    async def list_run_history(
        self,
        *,
        principal_id: str,
        organization_id: str = "unscoped",
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
            query = (
                select(WorkflowRunHistory)
                .where(WorkflowRunHistory.principal_id == principal_id)
                .where(WorkflowRunHistory.organization_id == organization_id)
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
        organization_id: str | None = None,
        membership_id: str | None = None,
        input_data: Mapping[str, object] | None = None,
    ) -> RunStatusRecord:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == thread_id)
                .with_for_update()
            )
            if (
                row is not None
                and organization_id is not None
                and row.organization_id != organization_id
            ):
                raise ActivityPersistenceError("run organization cannot change")
            started = (
                row.started_at
                if row and row.run_id == run_id
                else now.replace(tzinfo=None)
            )
            if row is None:
                row = WorkflowRun(
                    thread_id=thread_id,
                    run_id=run_id,
                    principal_id=principal_id or "unscoped",
                    organization_id=organization_id or "unscoped",
                    membership_id=membership_id or "unscoped",
                    started_at=started,
                )
                session.add(row)
            row.run_id = run_id
            if principal_id is not None:
                row.principal_id = principal_id
            if organization_id is not None:
                row.organization_id = organization_id
            if membership_id is not None:
                row.membership_id = membership_id
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
                        organization_id=organization_id or "unscoped",
                        membership_id=membership_id or "unscoped",
                        status=status,
                        started_at=started,
                        input_data=dict(input_data) if input_data is not None else None,
                    )
                    session.add(history)
            if history is not None:
                if principal_id is not None and history.principal_id != principal_id:
                    raise ActivityPersistenceError("run owner cannot change")
                if (
                    organization_id is not None
                    and history.organization_id != organization_id
                ):
                    raise ActivityPersistenceError("run organization cannot change")
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

    async def record_waiting_interaction(
        self,
        *,
        requested: InteractionRequested,
        principal_id: str,
        now: datetime,
        organization_id: str = "unscoped",
        membership_id: str = "unscoped",
    ) -> tuple[WorkflowEvent, ...]:
        identity = requested.identity
        async with AsyncSessionLocal() as session:
            run = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == identity.thread_id)
                .with_for_update()
            )
            if run is None or run.run_id != identity.run_id or run.status != "running":
                raise InteractionNotAvailableError("run cannot enter waiting state")
            history = await session.get(
                WorkflowRunHistory,
                (identity.thread_id, identity.run_id),
                with_for_update=True,
            )
            if (
                history is None
                or history.principal_id != principal_id
                or history.organization_id != organization_id
            ):
                raise InteractionNotAvailableError("run owner cannot change")
            existing = await session.scalar(
                select(WorkflowActivityEvent.event_id)
                .where(WorkflowActivityEvent.thread_id == identity.thread_id)
                .where(WorkflowActivityEvent.run_id == identity.run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.interaction")
                .where(
                    WorkflowActivityEvent.payload["identity"][
                        "interaction_id"
                    ].as_string()
                    == identity.interaction_id
                )
            )
            if existing is not None:
                raise ActivityPersistenceError("interaction identity already exists")
            interaction = WorkflowInteraction(
                identity=identity,
                kind=requested.request.type,
                status="pending",
                request=requested.request,
            )
            cursor = await session.get(
                WorkflowActivityCursor, identity.thread_id, with_for_update=True
            )
            start_seq = cursor.last_seq_id + 1 if cursor else 1
            events = self._create_events(
                (requested.activity, interaction),
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                first_seq=start_seq,
                now=now,
            )
            session.add_all(self._event_rows(events))
            self._advance_cursor(session, cursor, identity.thread_id, events[-1], now)
            run.status = "waiting"
            run.updated_at = now.replace(tzinfo=None)
            run.ended_at = None
            history.status = "waiting"
            history.updated_at = now.replace(tzinfo=None)
            history.ended_at = None
            await session.commit()
            return events

    async def claim_interaction_response(
        self,
        *,
        identity: InteractionIdentity,
        response: InteractionResponse,
        principal_id: str,
        now: datetime,
        organization_id: str = "unscoped",
        membership_id: str = "unscoped",
    ) -> ClaimedInteractionResume:
        async with AsyncSessionLocal() as session:
            run = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == identity.thread_id)
                .with_for_update()
            )
            if run is None or run.run_id != identity.run_id:
                raise InteractionNotAvailableError("run cannot accept this interaction")
            if run.status != "waiting":
                raise InteractionNotAvailableError("run is not waiting for input")

            interaction_row = await session.scalar(
                select(WorkflowActivityEvent)
                .where(WorkflowActivityEvent.thread_id == identity.thread_id)
                .where(WorkflowActivityEvent.run_id == identity.run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.interaction")
                .where(
                    WorkflowActivityEvent.payload["identity"][
                        "interaction_id"
                    ].as_string()
                    == identity.interaction_id
                )
                .order_by(WorkflowActivityEvent.seq_id.desc())
                .limit(1)
                .with_for_update()
            )
            interaction_event = (
                self._to_event(interaction_row) if interaction_row is not None else None
            )
            interaction = (
                interaction_event.payload
                if isinstance(interaction_event, WorkflowInteractionEvent)
                else None
            )
            activity_row = await session.scalar(
                select(WorkflowActivityEvent)
                .where(WorkflowActivityEvent.thread_id == identity.thread_id)
                .where(WorkflowActivityEvent.run_id == identity.run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.activity")
                .where(
                    WorkflowActivityEvent.payload["activity_id"].as_string()
                    == identity.activity_id
                )
                .order_by(WorkflowActivityEvent.seq_id.desc())
                .limit(1)
                .with_for_update()
            )
            activity_event = self._to_event(activity_row) if activity_row else None
            activity = (
                activity_event.payload
                if isinstance(activity_event, ActivityEvent)
                else None
            )
            if (
                interaction is None
                or interaction.identity != identity
                or interaction.status != "pending"
                or activity is None
                or activity.status != "waiting"
            ):
                raise InteractionNotAvailableError(
                    "interaction is stale or unavailable"
                )
            if response.type != interaction.request.type:
                raise InvalidInteractionResponseError(
                    "response type does not match the pending interaction"
                )
            if isinstance(interaction.request, TickerSelectionRequest):
                if not isinstance(response, TickerSelectionResponse) or (
                    response.selected_symbol
                    not in {item.symbol for item in interaction.request.candidates}
                ):
                    raise InvalidInteractionResponseError(
                        "selected symbol is not one of the available candidates"
                    )
            history = await session.get(
                WorkflowRunHistory,
                (identity.thread_id, identity.run_id),
                with_for_update=True,
            )
            if (
                history is None
                or history.principal_id != principal_id
                or history.organization_id != organization_id
            ):
                raise InteractionNotAvailableError("run owner cannot change")
            pending_resume = await session.get(
                WorkflowRunResume, identity.thread_id, with_for_update=True
            )
            if pending_resume is not None:
                raise InteractionNotAvailableError("run already has a resume command")
            cursor = await session.get(
                WorkflowActivityCursor, identity.thread_id, with_for_update=True
            )
            start_seq = cursor.last_seq_id + 1 if cursor else 1
            responded = interaction.model_copy(
                update={"status": "responded", "response": response}
            )
            resumed_activity = activity.model_copy(
                update={"status": "running", "attempt": activity.attempt + 1}
            )
            events = self._create_events(
                (responded, resumed_activity),
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                first_seq=start_seq,
                now=now,
            )
            session.add_all(self._event_rows(events))
            self._advance_cursor(session, cursor, identity.thread_id, events[-1], now)
            run.status = "running"
            run.updated_at = now.replace(tzinfo=None)
            run.ended_at = None
            history.status = "running"
            history.updated_at = now.replace(tzinfo=None)
            history.ended_at = None
            session.add(
                WorkflowRunResume(
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    principal_id=principal_id,
                    organization_id=history.organization_id,
                    membership_id=history.membership_id,
                    activity_id=identity.activity_id,
                    interaction_id=identity.interaction_id,
                    response=response.model_dump(mode="json"),
                    created_at=now.replace(tzinfo=None),
                )
            )
            await session.commit()
            return ClaimedInteractionResume(
                identity=identity,
                organization_id=history.organization_id,
                membership_id=history.membership_id,
                response=response,
                scope_path=activity.scope_path,
                attempt=resumed_activity.attempt,
                events=events,
            )

    async def cancel_run_with_interaction(
        self,
        *,
        thread_id: str,
        run_id: str,
        principal_id: str,
        now: datetime,
        organization_id: str = "unscoped",
    ) -> tuple[WorkflowEvent, ...]:
        async with AsyncSessionLocal() as session:
            run = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == thread_id)
                .with_for_update()
            )
            if run is None or run.run_id != run_id:
                raise InteractionNotAvailableError("run was not found")
            history = await session.get(
                WorkflowRunHistory, (thread_id, run_id), with_for_update=True
            )
            if (
                history is None
                or history.principal_id != principal_id
                or history.organization_id != organization_id
            ):
                raise InteractionNotAvailableError("run was not found")
            if run.status not in {"queued", "running", "waiting"}:
                return ()
            rows = (
                await session.scalars(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == thread_id)
                    .where(WorkflowActivityEvent.run_id == run_id)
                    .order_by(WorkflowActivityEvent.seq_id.asc())
                )
            ).all()
            latest_activities: dict[str, Activity] = {}
            latest_interactions: dict[str, WorkflowInteraction] = {}
            for row in rows:
                event = self._to_event(row)
                if isinstance(event, ActivityEvent):
                    latest_activities[event.payload.activity_id] = event.payload
                elif isinstance(event, WorkflowInteractionEvent):
                    latest_interactions[event.payload.identity.interaction_id] = (
                        event.payload
                    )
            payloads: list[Activity | WorkflowInteraction] = [
                interaction.model_copy(update={"status": "cancelled"})
                for interaction in latest_interactions.values()
                if interaction.status == "pending"
            ]
            payloads.extend(
                activity.model_copy(update={"status": "cancelled"})
                for activity in latest_activities.values()
                if activity.status in {"queued", "running", "waiting"}
            )
            if "workflow" not in latest_activities or latest_activities[
                "workflow"
            ].status not in {"queued", "running", "waiting"}:
                payloads.append(
                    Activity(
                        activity_id="workflow",
                        thread_id=thread_id,
                        run_id=run_id,
                        scope_path=("workflow",),
                        kind="phase",
                        status="cancelled",
                        label="Workflow cancelled",
                        attempt=1,
                    )
                )
            cursor = await session.get(
                WorkflowActivityCursor, thread_id, with_for_update=True
            )
            start_seq = cursor.last_seq_id + 1 if cursor else 1
            events = self._create_events(
                tuple(payloads),
                thread_id=thread_id,
                run_id=run_id,
                first_seq=start_seq,
                now=now,
            )
            if events:
                session.add_all(self._event_rows(events))
                self._advance_cursor(session, cursor, thread_id, events[-1], now)
            run.status = "cancelled"
            run.updated_at = now.replace(tzinfo=None)
            run.ended_at = now.replace(tzinfo=None)
            history.status = "cancelled"
            history.updated_at = now.replace(tzinfo=None)
            history.ended_at = now.replace(tzinfo=None)
            pending_resume = await session.get(
                WorkflowRunResume, thread_id, with_for_update=True
            )
            if pending_resume is not None:
                await session.delete(pending_resume)
            await session.commit()
            return events

    async def pending_resumes(self) -> tuple[PendingResume, ...]:
        async with AsyncSessionLocal() as session:
            pending_rows = (await session.scalars(select(WorkflowRunResume))).all()
            pending: list[PendingResume] = []
            for row in pending_rows:
                run = await session.get(WorkflowRun, row.thread_id)
                if run is None or run.run_id != row.run_id or run.status != "running":
                    continue
                interaction_row = await session.scalar(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == row.thread_id)
                    .where(WorkflowActivityEvent.run_id == row.run_id)
                    .where(WorkflowActivityEvent.event_name == "workflow.interaction")
                    .where(
                        WorkflowActivityEvent.payload["identity"][
                            "interaction_id"
                        ].as_string()
                        == row.interaction_id
                    )
                    .order_by(WorkflowActivityEvent.seq_id.desc())
                    .limit(1)
                )
                interaction_event = (
                    self._to_event(interaction_row) if interaction_row else None
                )
                interaction = (
                    interaction_event.payload
                    if isinstance(interaction_event, WorkflowInteractionEvent)
                    else None
                )
                event_row = await session.scalar(
                    select(WorkflowActivityEvent)
                    .where(WorkflowActivityEvent.thread_id == row.thread_id)
                    .where(WorkflowActivityEvent.run_id == row.run_id)
                    .where(WorkflowActivityEvent.event_name == "workflow.activity")
                    .where(
                        WorkflowActivityEvent.payload["activity_id"].as_string()
                        == row.activity_id
                    )
                    .order_by(WorkflowActivityEvent.seq_id.desc())
                    .limit(1)
                )
                activity_event = self._to_event(event_row) if event_row else None
                activity = (
                    activity_event.payload
                    if isinstance(activity_event, ActivityEvent)
                    else None
                )
                if (
                    interaction is None
                    or interaction.status != "responded"
                    or interaction.response
                    != TypeAdapter(InteractionResponse).validate_python(row.response)
                    or activity is None
                    or activity.status != "running"
                ):
                    continue
                pending.append(
                    PendingResume(
                        identity=interaction.identity,
                        principal_id=row.principal_id,
                        organization_id=row.organization_id,
                        membership_id=row.membership_id,
                        scope_path=activity.scope_path,
                        attempt=activity.attempt,
                        response=TypeAdapter(InteractionResponse).validate_python(
                            row.response
                        ),
                    )
                )
            return tuple(pending)

    async def begin_retry(
        self,
        *,
        principal_id: str,
        thread_id: str,
        source_run_id: str,
        checkpoint: CheckpointIdentity,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
        organization_id: str = "unscoped",
        membership_id: str = "unscoped",
    ) -> tuple[RetryOperation, bool]:
        async with AsyncSessionLocal() as session:
            existing = await session.scalar(
                select(WorkflowRetryOperation)
                .where(WorkflowRetryOperation.principal_id == principal_id)
                .where(WorkflowRetryOperation.idempotency_key == idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                if (
                    existing.request_hash != request_hash
                    or existing.organization_id != organization_id
                ):
                    raise RetryIdempotencyConflictError(
                        "idempotency key was already used for another retry command"
                    )
                return self._retry_from_model(existing), False

            source = await session.get(
                WorkflowRunHistory, (thread_id, source_run_id), with_for_update=True
            )
            if (
                source is None
                or source.principal_id != principal_id
                or source.organization_id != organization_id
            ):
                raise RetryNotAvailableError("source run was not found")
            if source.status != "failed":
                raise RetryNotAvailableError("only a failed run may be retried")
            failure_row = await session.scalar(
                select(WorkflowActivityEvent)
                .where(WorkflowActivityEvent.thread_id == thread_id)
                .where(WorkflowActivityEvent.run_id == source_run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.activity")
                .where(
                    WorkflowActivityEvent.payload["activity_id"].as_string()
                    == "workflow"
                )
                .order_by(WorkflowActivityEvent.seq_id.desc())
                .limit(1)
            )
            failure_event = self._to_event(failure_row) if failure_row else None
            failure = (
                failure_event.payload.failure
                if isinstance(failure_event, ActivityEvent)
                else None
            )
            if failure is None or not failure.retryable:
                raise RetryNotAvailableError("source failure is not retryable")
            if failure.checkpoint != checkpoint:
                raise InvalidCheckpointError("checkpoint does not match the failed run")
            current = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.thread_id == thread_id)
                .with_for_update()
            )
            if current and current.status in {"queued", "running", "waiting"}:
                existing = await session.scalar(
                    select(WorkflowRetryOperation)
                    .where(WorkflowRetryOperation.principal_id == principal_id)
                    .where(WorkflowRetryOperation.idempotency_key == idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    if (
                        existing.request_hash != request_hash
                        or existing.organization_id != organization_id
                    ):
                        raise RetryIdempotencyConflictError(
                            "idempotency key was already used for another retry command"
                        )
                    return self._retry_from_model(existing), False
                raise RetryAlreadyActiveError("thread already has an active run")
            attempt_row = await session.scalar(
                select(func.max(WorkflowRetryOperation.attempt))
                .where(WorkflowRetryOperation.thread_id == thread_id)
                .where(WorkflowRetryOperation.source_run_id == source_run_id)
            )
            attempt = int(attempt_row or 0) + 1
            target_run_id = str(uuid.uuid4())
            operation = WorkflowRetryOperation(
                operation_id=str(uuid.uuid4()),
                thread_id=thread_id,
                source_run_id=source_run_id,
                target_run_id=target_run_id,
                principal_id=principal_id,
                organization_id=organization_id,
                membership_id=membership_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                checkpoint=checkpoint.model_dump(mode="json"),
                attempt=attempt,
                status="queued",
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
            session.add(operation)
            if current is None:
                current = WorkflowRun(
                    thread_id=thread_id,
                    run_id=target_run_id,
                    status="queued",
                    principal_id=principal_id,
                    organization_id=organization_id,
                    membership_id=membership_id,
                    started_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                )
                session.add(current)
            else:
                current.run_id = target_run_id
                current.status = "queued"
                current.principal_id = principal_id
                current.organization_id = organization_id
                current.membership_id = membership_id
                current.started_at = now.replace(tzinfo=None)
                current.updated_at = now.replace(tzinfo=None)
                current.ended_at = None
            session.add(
                WorkflowRunHistory(
                    thread_id=thread_id,
                    run_id=target_run_id,
                    principal_id=principal_id,
                    organization_id=organization_id,
                    membership_id=membership_id,
                    status="queued",
                    started_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                    input_data={
                        "retry": {
                            "source_run_id": source_run_id,
                            "checkpoint": checkpoint.model_dump(mode="json"),
                        }
                    },
                    source_run_id=source_run_id,
                    retry_operation_id=operation.operation_id,
                    attempt=attempt,
                    checkpoint=checkpoint.model_dump(mode="json"),
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(WorkflowRetryOperation)
                    .where(WorkflowRetryOperation.principal_id == principal_id)
                    .where(WorkflowRetryOperation.idempotency_key == idempotency_key)
                )
                if existing is not None and existing.request_hash == request_hash:
                    return self._retry_from_model(existing), False
                raise
            return self._retry_from_model(operation), True

    async def set_retry_status(
        self,
        *,
        operation_id: str,
        status: str,
        now: datetime,
        outcome: str | None = None,
    ) -> RetryOperation:
        async with AsyncSessionLocal() as session:
            row = await session.get(
                WorkflowRetryOperation, operation_id, with_for_update=True
            )
            if row is None:
                raise RetryNotAvailableError("retry operation was not found")
            operation = self._retry_from_model(row)
            if not operation.can_transition_to(status):
                raise InvalidRetryTransitionError(
                    f"cannot transition retry from {operation.status} to {status}"
                )
            if (
                row.status in {"completed", "failed", "cancelled"}
                and status == "running"
            ):
                return self._retry_from_model(row)
            row.status = status
            row.outcome = outcome
            row.updated_at = now.replace(tzinfo=None)
            row.ended_at = (
                now.replace(tzinfo=None)
                if status in {"completed", "failed", "cancelled"}
                else None
            )
            await session.commit()
            return self._retry_from_model(row)

    async def claim_retry(
        self, *, operation_id: str, now: datetime, lease_seconds: float
    ) -> RetryOperation | None:
        cutoff = now.replace(tzinfo=None) - timedelta(seconds=lease_seconds)
        async with AsyncSessionLocal() as session:
            row = await session.get(
                WorkflowRetryOperation, operation_id, with_for_update=True
            )
            if row is None or row.status in {"completed", "failed", "cancelled"}:
                return None
            if row.status == "running" and row.updated_at > cutoff:
                return None
            row.status = "running"
            row.updated_at = now.replace(tzinfo=None)
            row.ended_at = None
            row.outcome = None
            await session.commit()
            return self._retry_from_model(row)

    async def pending_retries(
        self, *, now: datetime, lease_seconds: float
    ) -> tuple[RetryOperation, ...]:
        cutoff = now.replace(tzinfo=None) - timedelta(seconds=lease_seconds)
        async with AsyncSessionLocal() as session:
            rows = (
                await session.scalars(
                    select(WorkflowRetryOperation)
                    .where(
                        or_(
                            WorkflowRetryOperation.status == "queued",
                            and_(
                                WorkflowRetryOperation.status == "running",
                                WorkflowRetryOperation.updated_at <= cutoff,
                            ),
                        )
                    )
                    .order_by(WorkflowRetryOperation.created_at.asc())
                )
            ).all()
        return tuple(self._retry_from_model(row) for row in rows)

    async def retry_for_run(
        self, *, thread_id: str, run_id: str
    ) -> RetryOperation | None:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(WorkflowRetryOperation)
                .where(WorkflowRetryOperation.thread_id == thread_id)
                .where(
                    or_(
                        WorkflowRetryOperation.source_run_id == run_id,
                        WorkflowRetryOperation.target_run_id == run_id,
                    )
                )
                .order_by(WorkflowRetryOperation.created_at.desc())
                .limit(1)
            )
        return self._retry_from_model(row) if row else None

    @staticmethod
    def _to_event(row: WorkflowActivityEvent) -> WorkflowEvent:
        return _EVENT_ADAPTER.validate_python(
            {
                "event_id": row.event_id,
                "seq_id": row.seq_id,
                "event_version": row.event_version,
                "event_name": row.event_name,
                "thread_id": row.thread_id,
                "run_id": row.run_id,
                "occurred_at": row.occurred_at.replace(tzinfo=timezone.utc),
                "payload": row.payload,
            }
        )

    @staticmethod
    def _create_events(
        payloads: tuple[Activity | WorkflowInteraction | WorkflowAgentOutput, ...],
        *,
        thread_id: str,
        run_id: str,
        first_seq: int,
        now: datetime,
    ) -> tuple[WorkflowEvent, ...]:
        events: list[WorkflowEvent] = []
        for offset, payload in enumerate(payloads):
            envelope = {
                "event_id": str(uuid.uuid4()),
                "seq_id": first_seq + offset,
                "thread_id": thread_id,
                "run_id": run_id,
                "occurred_at": now,
                "payload": payload,
            }
            if isinstance(payload, Activity):
                events.append(ActivityEvent(**envelope, event_version="v2"))
            elif isinstance(payload, WorkflowInteraction):
                events.append(WorkflowInteractionEvent(**envelope))
            else:
                events.append(WorkflowAgentOutputEvent(**envelope))
        return tuple(events)

    @staticmethod
    def _event_rows(events: tuple[WorkflowEvent, ...]) -> list[WorkflowActivityEvent]:
        return [
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
            for event in events
        ]

    @staticmethod
    def _advance_cursor(
        session,
        cursor: WorkflowActivityCursor | None,
        thread_id: str,
        last_event: WorkflowEvent,
        now: datetime,
    ) -> None:
        if cursor is None:
            session.add(
                WorkflowActivityCursor(
                    thread_id=thread_id,
                    last_seq_id=last_event.seq_id,
                    updated_at=now.replace(tzinfo=None),
                )
            )
        else:
            cursor.last_seq_id = last_event.seq_id
            cursor.updated_at = now.replace(tzinfo=None)

    @staticmethod
    def _run_from_model(row: WorkflowRun) -> RunStatusRecord:
        return RunStatusRecord(
            thread_id=row.thread_id,
            run_id=row.run_id,
            principal_id=row.principal_id,
            organization_id=row.organization_id,
            membership_id=row.membership_id,
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
            principal_id=row.principal_id,
            organization_id=row.organization_id,
            membership_id=row.membership_id,
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
            source_run_id=row.source_run_id,
            retry_operation_id=row.retry_operation_id,
            attempt=row.attempt,
            checkpoint=CheckpointIdentity.model_validate(row.checkpoint)
            if row.checkpoint
            else None,
        )

    @staticmethod
    def _retry_from_model(row: WorkflowRetryOperation) -> RetryOperation:
        return RetryOperation(
            operation_id=row.operation_id,
            thread_id=row.thread_id,
            source_run_id=row.source_run_id,
            target_run_id=row.target_run_id,
            principal_id=row.principal_id,
            organization_id=row.organization_id,
            membership_id=row.membership_id,
            idempotency_key=row.idempotency_key,
            request_hash=row.request_hash,
            checkpoint=CheckpointIdentity.model_validate(row.checkpoint),
            attempt=row.attempt,
            status=row.status,
            outcome=row.outcome,
            created_at=row.created_at.replace(tzinfo=timezone.utc),
            updated_at=row.updated_at.replace(tzinfo=timezone.utc),
            ended_at=row.ended_at.replace(tzinfo=timezone.utc)
            if row.ended_at
            else None,
        )
