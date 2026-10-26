from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    AnalysisRunPage,
    AnalysisRunRecord,
    ClaimedInteractionResume,
    InteractionIdentity,
    InteractionRequested,
    PendingResume,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
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
    InvalidCursorError,
    InvalidInteractionResponseError,
    ReplayGapError,
)


class InMemoryActivityRepository:
    """Deterministic repository used by tests and local composition."""

    def __init__(self, *, replay_retention: int = 10_000) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, list[WorkflowEvent]] = defaultdict(list)
        self._event_ids: dict[str, set[str]] = defaultdict(set)
        self._cursors: dict[str, int] = defaultdict(int)
        self._runs: dict[str, RunStatusRecord] = {}
        self._pending_resumes: dict[str, PendingResume] = {}
        self._run_history: dict[tuple[str, str], AnalysisRunRecord] = {}
        self._run_owners: dict[tuple[str, str], str] = {}
        self._retention = replay_retention

    async def append_atomic(
        self, event: WorkflowEvent, *, run_status: RunStatus | None = None
    ) -> bool:
        async with self._lock:
            events = self._events[event.thread_id]
            if event.event_id in self._event_ids[event.thread_id]:
                return False
            expected = self._cursors[event.thread_id] + 1
            if event.seq_id != expected:
                raise ActivityPersistenceError(
                    f"sequence must advance from {self._cursors[event.thread_id]} to {event.seq_id}"
                )
            if event.seq_id < 1:
                raise ActivityPersistenceError("event sequence is not append-only")
            if any(existing.seq_id == event.seq_id for existing in events):
                raise ActivityPersistenceError("event sequence already exists")
            if run_status is not None:
                run = self._runs.get(event.thread_id)
                if run is None or run.run_id != event.run_id:
                    raise ActivityPersistenceError(
                        "run status does not match activity event"
                    )
                self._runs[event.thread_id] = run.model_copy(
                    update={
                        "status": run_status,
                        "updated_at": event.occurred_at,
                        "ended_at": event.occurred_at
                        if run_status in {"completed", "failed", "cancelled"}
                        else None,
                    }
                )
                history_key = (event.thread_id, event.run_id)
                history = self._run_history.get(history_key)
                if history is not None:
                    self._run_history[history_key] = history.model_copy(
                        update={
                            "status": run_status,
                            "updated_at": event.occurred_at,
                            "ended_at": event.occurred_at
                            if run_status in {"completed", "failed", "cancelled"}
                            else None,
                        }
                    )
                if run_status in {"waiting", "completed", "failed", "cancelled"}:
                    self._pending_resumes.pop(event.thread_id, None)
            events.append(event)
            self._cursors[event.thread_id] = event.seq_id
            self._event_ids[event.thread_id].add(event.event_id)
            if len(events) > self._retention:
                removed = events.pop(0)
                self._event_ids[event.thread_id].discard(removed.event_id)
            return True

    async def replay(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int,
    ) -> ReplayPage:
        if after_seq < 0:
            raise InvalidCursorError("cursor must be non-negative")
        if limit < 1:
            raise InvalidCursorError("replay limit must be positive")
        async with self._lock:
            events = self._events.get(thread_id, [])
            if events and after_seq < events[0].seq_id - 1:
                raise ReplayGapError(events[0].seq_id, after_seq)
            selected = [event for event in events if event.seq_id > after_seq]
            page = selected[:limit]
            cursor = (
                page[-1].seq_id if page else max(self._cursors[thread_id], after_seq)
            )
            return ReplayPage(
                events=tuple(page), cursor=cursor, has_more=len(selected) > len(page)
            )

    async def snapshot(self, *, thread_id: str, run_id: str) -> WorkflowSnapshot:
        async with self._lock:
            events = tuple(self._events.get(thread_id, ()))
            latest: dict[str, ActivityEvent] = {}
            interactions: dict[str, WorkflowInteraction] = {}
            outputs: dict[str, WorkflowAgentOutput] = {}
            for event in events:
                if event.run_id == run_id:
                    match event:
                        case ActivityEvent():
                            latest[event.payload.activity_id] = event
                        case WorkflowInteractionEvent():
                            interactions[event.payload.identity.interaction_id] = (
                                event.payload
                            )
                        case WorkflowAgentOutputEvent():
                            outputs[
                                f"{event.payload.identity.activity_id}:{event.payload.agent_id}"
                            ] = event.payload
            active_statuses = {"queued", "running", "waiting"}
            active = tuple(
                event.payload
                for event in latest.values()
                if event.payload.status in active_statuses
            )
            recent = tuple(
                event.payload
                for event in reversed(events)
                if event.run_id == run_id and isinstance(event, ActivityEvent)
            )[:50]
            run = self._run_history.get((thread_id, run_id))
            status: RunStatus = run.status if run else "queued"
            return WorkflowSnapshot(
                thread_id=thread_id,
                run_id=run_id,
                run_status=status,
                cursor=self._cursors[thread_id],
                active_activities=active,
                recent_activities=recent,
                pending_interactions=tuple(
                    interaction
                    for interaction in interactions.values()
                    if interaction.status == "pending"
                ),
                completed_outputs=tuple(outputs.values()),
            )

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None:
        async with self._lock:
            return self._runs.get(thread_id)

    async def get_run_history(
        self, *, principal_id: str, thread_id: str, run_id: str
    ) -> AnalysisRunRecord | None:
        async with self._lock:
            key = (thread_id, run_id)
            record = self._run_history.get(key)
            return (
                record if record and self._run_owners.get(key) == principal_id else None
            )

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
        async with self._lock:
            records = sorted(
                (
                    record
                    for record in self._run_history.values()
                    if self._run_owners.get((record.thread_id, record.run_id))
                    == principal_id
                ),
                key=lambda record: (
                    record.started_at is not None,
                    record.started_at or datetime.min.replace(tzinfo=timezone.utc),
                    record.thread_id,
                    record.run_id,
                ),
                reverse=True,
            )
            if before_thread_id is not None and before_run_id is not None:
                if before_started_at is None:
                    records = [
                        record
                        for record in records
                        if record.started_at is None
                        and (record.thread_id, record.run_id)
                        < (before_thread_id, before_run_id)
                    ]
                else:
                    marker = (
                        before_started_at,
                        before_thread_id,
                        before_run_id,
                    )
                    records = [
                        record
                        for record in records
                        if record.started_at is None
                        or (record.started_at, record.thread_id, record.run_id) < marker
                    ]
            selected = records[:limit]
            has_more = len(records) > limit
            last = selected[-1] if selected else None
            return AnalysisRunPage(
                runs=tuple(selected),
                has_more=has_more,
                next_started_at=last.started_at if has_more and last else None,
                next_thread_id=last.thread_id if has_more and last else None,
                next_run_id=last.run_id if has_more and last else None,
            )

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
        async with self._lock:
            previous = self._runs.get(thread_id)
            started_at = (
                previous.started_at if previous and previous.run_id == run_id else now
            )
            record = RunStatusRecord(
                thread_id=thread_id,
                run_id=run_id,
                status=status,
                started_at=started_at,
                updated_at=now,
                ended_at=now
                if status in {"completed", "failed", "cancelled"}
                else None,
            )
            self._runs[thread_id] = record
            if status in {"completed", "failed", "cancelled"}:
                self._pending_resumes.pop(thread_id, None)
            if principal_id is not None:
                self._run_owners[(thread_id, run_id)] = principal_id
                previous_history = self._run_history.get((thread_id, run_id))
                self._run_history[(thread_id, run_id)] = AnalysisRunRecord(
                    thread_id=thread_id,
                    run_id=run_id,
                    status=status,
                    started_at=previous_history.started_at
                    if previous_history
                    else started_at,
                    updated_at=now,
                    ended_at=record.ended_at,
                    input_data=(
                        previous_history.input_data
                        if previous_history and previous_history.input_data is not None
                        else dict(input_data)
                        if input_data is not None
                        else None
                    ),
                )
            return record

    async def record_waiting_interaction(
        self,
        *,
        requested: InteractionRequested,
        principal_id: str,
        now: datetime,
    ) -> tuple[WorkflowEvent, ...]:
        async with self._lock:
            identity = requested.identity
            run_key = (identity.thread_id, identity.run_id)
            run = self._runs.get(identity.thread_id)
            if (
                run is None
                or run.run_id != identity.run_id
                or self._run_owners.get(run_key) != principal_id
            ):
                raise InteractionNotAvailableError("run owner cannot change")
            if run.status not in {"running", "queued"}:
                raise ActivityPersistenceError("run cannot enter waiting state")
            if any(
                isinstance(event, WorkflowInteractionEvent)
                and event.payload.identity.interaction_id == identity.interaction_id
                for event in self._events[identity.thread_id]
            ):
                raise ActivityPersistenceError("interaction identity already exists")
            interaction = WorkflowInteraction(
                identity=identity,
                kind=requested.request.type,
                status="pending",
                request=requested.request,
            )
            events = self._create_events(
                (requested.activity, interaction),
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                now=now,
            )
            self._append_batch_unlocked(events)
            self._set_run_state_unlocked(
                identity.thread_id, identity.run_id, "waiting", now
            )
            return events

    async def claim_interaction_response(
        self,
        *,
        identity: InteractionIdentity,
        response: TickerSelectionResponse,
        principal_id: str,
        now: datetime,
    ) -> ClaimedInteractionResume:
        async with self._lock:
            run = self._runs.get(identity.thread_id)
            run_key = (identity.thread_id, identity.run_id)
            if (
                run is None
                or run.run_id != identity.run_id
                or run.status != "waiting"
                or self._run_owners.get(run_key) != principal_id
            ):
                raise InteractionNotAvailableError("run cannot accept this interaction")
            interaction = next(
                (
                    event.payload
                    for event in reversed(self._events[identity.thread_id])
                    if isinstance(event, WorkflowInteractionEvent)
                    and event.payload.identity == identity
                ),
                None,
            )
            activity = next(
                (
                    event.payload
                    for event in reversed(self._events[identity.thread_id])
                    if isinstance(event, ActivityEvent)
                    and event.run_id == identity.run_id
                    and event.payload.activity_id == identity.activity_id
                ),
                None,
            )
            if (
                interaction is None
                or interaction.status != "pending"
                or activity is None
                or activity.status != "waiting"
            ):
                raise InteractionNotAvailableError(
                    "interaction is stale or unavailable"
                )
            if response.selected_symbol not in {
                candidate.symbol for candidate in interaction.request.candidates
            }:
                raise InvalidInteractionResponseError(
                    "selected symbol is not one of the available candidates"
                )
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
                now=now,
            )
            self._append_batch_unlocked(events)
            self._set_run_state_unlocked(
                identity.thread_id, identity.run_id, "running", now
            )
            self._pending_resumes[identity.thread_id] = PendingResume(
                identity=identity,
                principal_id=principal_id,
                response=response,
                scope_path=activity.scope_path,
                attempt=resumed_activity.attempt,
            )
            return ClaimedInteractionResume(
                identity=identity,
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
    ) -> tuple[WorkflowEvent, ...]:
        async with self._lock:
            run = self._runs.get(thread_id)
            if (
                run is None
                or run.run_id != run_id
                or self._run_owners.get((thread_id, run_id)) != principal_id
            ):
                raise InteractionNotAvailableError("run was not found")
            if run.status not in {"queued", "running", "waiting"}:
                return ()

            latest_activities: dict[str, Activity] = {}
            latest_interactions: dict[str, WorkflowInteraction] = {}
            for event in self._events[thread_id]:
                if event.run_id != run_id:
                    continue
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
            events = self._create_events(
                tuple(payloads), thread_id=thread_id, run_id=run_id, now=now
            )
            self._append_batch_unlocked(events)
            self._set_run_state_unlocked(thread_id, run_id, "cancelled", now)
            self._pending_resumes.pop(thread_id, None)
            return events

    async def pending_resumes(self) -> tuple[PendingResume, ...]:
        async with self._lock:
            return tuple(self._pending_resumes.values())

    def _create_events(
        self,
        payloads: tuple[Activity | WorkflowInteraction | WorkflowAgentOutput, ...],
        *,
        thread_id: str,
        run_id: str,
        now: datetime,
    ) -> tuple[WorkflowEvent, ...]:
        events: list[WorkflowEvent] = []
        sequence = self._cursors[thread_id]
        for payload in payloads:
            sequence += 1
            envelope = {
                "event_id": str(uuid.uuid4()),
                "seq_id": sequence,
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

    def _append_batch_unlocked(self, events: tuple[WorkflowEvent, ...]) -> None:
        if events and events[0].seq_id != self._cursors[events[0].thread_id] + 1:
            raise ActivityPersistenceError("event batch cursor changed before commit")
        for previous, current in zip(events, events[1:], strict=False):
            if current.seq_id != previous.seq_id + 1:
                raise ActivityPersistenceError("event batch sequence contains a gap")
        for event in events:
            self._events[event.thread_id].append(event)
            self._event_ids[event.thread_id].add(event.event_id)
            self._cursors[event.thread_id] = event.seq_id

    def _set_run_state_unlocked(
        self, thread_id: str, run_id: str, status: RunStatus, now: datetime
    ) -> None:
        run = self._runs[thread_id]
        ended_at = now if status in {"completed", "failed", "cancelled"} else None
        self._runs[thread_id] = run.model_copy(
            update={"status": status, "updated_at": now, "ended_at": ended_at}
        )
        history_key = (thread_id, run_id)
        history = self._run_history.get(history_key)
        if history is not None:
            self._run_history[history_key] = history.model_copy(
                update={"status": status, "updated_at": now, "ended_at": ended_at}
            )
