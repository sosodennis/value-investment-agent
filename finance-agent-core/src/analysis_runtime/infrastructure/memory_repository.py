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
        self._retry_operations: dict[str, RetryOperation] = {}
        self._retry_by_key: dict[tuple[str, str], str] = {}
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
            failure = None
            for event in events:
                if event.run_id == run_id:
                    match event:
                        case ActivityEvent():
                            latest[event.payload.activity_id] = event
                            if (
                                event.payload.activity_id == "workflow"
                                and event.payload.failure is not None
                            ):
                                failure = event.payload.failure
                        case WorkflowInteractionEvent():
                            interactions[event.payload.identity.interaction_id] = (
                                event.payload
                            )
                        case WorkflowAgentOutputEvent():
                            outputs[
                                f"{event.payload.identity.activity_id}:{event.payload.agent_id}"
                            ] = event.payload
            active_statuses = {"queued", "running", "waiting"}
            run = self._run_history.get((thread_id, run_id))
            status: RunStatus = run.status if run else "queued"
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
            recent = tuple(
                event.payload.model_copy(update={"status": terminal_status})
                if terminal_status and event.payload.status in active_statuses
                else event.payload
                for event in reversed(events)
                if event.run_id == run_id and isinstance(event, ActivityEvent)
            )[:50]
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
                failure=failure,
                retry_operation=self._retry_view_for_run_unlocked(
                    thread_id=thread_id, run_id=run_id
                ),
            )

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None:
        async with self._lock:
            return self._runs.get(thread_id)

    async def get_run_history(
        self,
        *,
        principal_id: str,
        organization_id: str = "unscoped",
        thread_id: str,
        run_id: str,
    ) -> AnalysisRunRecord | None:
        async with self._lock:
            key = (thread_id, run_id)
            record = self._run_history.get(key)
            return (
                record
                if record
                and self._run_owners.get(key) == principal_id
                and record.organization_id == organization_id
                else None
            )

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
        async with self._lock:
            records = sorted(
                (
                    record
                    for record in self._run_history.values()
                    if self._run_owners.get((record.thread_id, record.run_id))
                    == principal_id
                    and record.organization_id == organization_id
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
        organization_id: str | None = None,
        membership_id: str | None = None,
        input_data: Mapping[str, object] | None = None,
    ) -> RunStatusRecord:
        async with self._lock:
            previous = self._runs.get(thread_id)
            if (
                previous is not None
                and organization_id is not None
                and previous.organization_id != organization_id
            ):
                raise ActivityPersistenceError("run organization cannot change")
            started_at = (
                previous.started_at if previous and previous.run_id == run_id else now
            )
            record = RunStatusRecord(
                thread_id=thread_id,
                run_id=run_id,
                principal_id=principal_id or "unscoped",
                organization_id=organization_id or "unscoped",
                membership_id=membership_id or "unscoped",
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
                    principal_id=principal_id,
                    organization_id=organization_id or "unscoped",
                    membership_id=membership_id or "unscoped",
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
                    source_run_id=previous_history.source_run_id
                    if previous_history
                    else None,
                    retry_operation_id=previous_history.retry_operation_id
                    if previous_history
                    else None,
                    attempt=previous_history.attempt if previous_history else 1,
                    checkpoint=previous_history.checkpoint
                    if previous_history
                    else None,
                )
            return record

    async def record_waiting_interaction(
        self,
        *,
        requested: InteractionRequested,
        principal_id: str,
        now: datetime,
        organization_id: str = "unscoped",
        membership_id: str = "unscoped",
    ) -> tuple[WorkflowEvent, ...]:
        async with self._lock:
            identity = requested.identity
            run_key = (identity.thread_id, identity.run_id)
            run = self._runs.get(identity.thread_id)
            if (
                run is None
                or run.run_id != identity.run_id
                or self._run_owners.get(run_key) != principal_id
                or run.organization_id != organization_id
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
        response: InteractionResponse,
        principal_id: str,
        now: datetime,
        organization_id: str = "unscoped",
        membership_id: str = "unscoped",
    ) -> ClaimedInteractionResume:
        async with self._lock:
            run = self._runs.get(identity.thread_id)
            run_key = (identity.thread_id, identity.run_id)
            if (
                run is None
                or run.run_id != identity.run_id
                or run.status != "waiting"
                or self._run_owners.get(run_key) != principal_id
                or run.organization_id != organization_id
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
            if response.type != interaction.request.type:
                raise InvalidInteractionResponseError(
                    "response type does not match the pending interaction"
                )
            if isinstance(interaction.request, TickerSelectionRequest):
                if not isinstance(response, TickerSelectionResponse) or (
                    response.selected_symbol
                    not in {
                        candidate.symbol for candidate in interaction.request.candidates
                    }
                ):
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
                organization_id=run.organization_id,
                membership_id=run.membership_id,
                response=response,
                scope_path=activity.scope_path,
                attempt=resumed_activity.attempt,
            )
            return ClaimedInteractionResume(
                identity=identity,
                organization_id=run.organization_id,
                membership_id=run.membership_id,
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
        async with self._lock:
            run = self._runs.get(thread_id)
            if (
                run is None
                or run.run_id != run_id
                or self._run_owners.get((thread_id, run_id)) != principal_id
                or run.organization_id != organization_id
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
        async with self._lock:
            existing_id = self._retry_by_key.get((principal_id, idempotency_key))
            if existing_id is not None:
                existing = self._retry_operations[existing_id]
                if (
                    existing.request_hash != request_hash
                    or existing.organization_id != organization_id
                ):
                    raise RetryIdempotencyConflictError(
                        "idempotency key was already used for another retry command"
                    )
                return existing, False
            source = self._run_history.get((thread_id, source_run_id))
            if (
                source is None
                or self._run_owners.get((thread_id, source_run_id)) != principal_id
                or source.organization_id != organization_id
            ):
                raise RetryNotAvailableError("source run was not found")
            if source.status != "failed":
                raise RetryNotAvailableError("only a failed run may be retried")
            source_snapshot = await self._snapshot_unlocked(thread_id, source_run_id)
            if source_snapshot.failure is None or not source_snapshot.failure.retryable:
                raise RetryNotAvailableError("source failure is not retryable")
            if source_snapshot.failure.checkpoint != checkpoint:
                raise InvalidCheckpointError("checkpoint does not match the failed run")
            current = self._runs.get(thread_id)
            if current and current.status in {"queued", "running", "waiting"}:
                raise RetryAlreadyActiveError("thread already has an active run")
            attempt = 1 + max(
                (
                    operation.attempt
                    for operation in self._retry_operations.values()
                    if operation.thread_id == thread_id
                    and operation.source_run_id == source_run_id
                ),
                default=0,
            )
            target_run_id = str(uuid.uuid4())
            operation = RetryOperation(
                operation_id=str(uuid.uuid4()),
                thread_id=thread_id,
                source_run_id=source_run_id,
                target_run_id=target_run_id,
                principal_id=principal_id,
                organization_id=organization_id,
                membership_id=membership_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                checkpoint=checkpoint,
                attempt=attempt,
                status="queued",
                created_at=now,
                updated_at=now,
            )
            self._retry_operations[operation.operation_id] = operation
            self._retry_by_key[(principal_id, idempotency_key)] = operation.operation_id
            self._runs[thread_id] = RunStatusRecord(
                thread_id=thread_id,
                run_id=target_run_id,
                principal_id=principal_id,
                organization_id=organization_id,
                membership_id=membership_id,
                status="queued",
                started_at=now,
                updated_at=now,
            )
            self._run_owners[(thread_id, target_run_id)] = principal_id
            self._run_history[(thread_id, target_run_id)] = AnalysisRunRecord(
                thread_id=thread_id,
                run_id=target_run_id,
                status="queued",
                principal_id=principal_id,
                organization_id=organization_id,
                membership_id=membership_id,
                started_at=now,
                updated_at=now,
                input_data={
                    "retry": {
                        "source_run_id": source_run_id,
                        "checkpoint": checkpoint.model_dump(mode="json"),
                    }
                },
                source_run_id=source_run_id,
                retry_operation_id=operation.operation_id,
                attempt=attempt,
                checkpoint=checkpoint,
            )
            return operation, True

    async def set_retry_status(
        self,
        *,
        operation_id: str,
        status: str,
        now: datetime,
        outcome: str | None = None,
    ) -> RetryOperation:
        async with self._lock:
            operation = self._retry_operations.get(operation_id)
            if operation is None:
                raise RetryNotAvailableError("retry operation was not found")
            if not operation.can_transition_to(status):
                raise InvalidRetryTransitionError(
                    f"cannot transition retry from {operation.status} to {status}"
                )
            if (
                operation.status in {"completed", "failed", "cancelled"}
                and status == "running"
            ):
                return operation
            ended_at = now if status in {"completed", "failed", "cancelled"} else None
            updated = operation.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "ended_at": ended_at,
                    "outcome": outcome,
                }
            )
            self._retry_operations[operation_id] = updated
            return updated

    async def claim_retry(
        self, *, operation_id: str, now: datetime, lease_seconds: float
    ) -> RetryOperation | None:
        async with self._lock:
            operation = self._retry_operations.get(operation_id)
            if operation is None or operation.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                return None
            lease_expired = (
                operation.status == "running"
                and (now - operation.updated_at).total_seconds() >= lease_seconds
            )
            if operation.status == "running" and not lease_expired:
                return None
            claimed = operation.model_copy(
                update={
                    "status": "running",
                    "updated_at": now,
                    "ended_at": None,
                    "outcome": None,
                }
            )
            self._retry_operations[operation_id] = claimed
            return claimed

    async def pending_retries(
        self, *, now: datetime, lease_seconds: float
    ) -> tuple[RetryOperation, ...]:
        async with self._lock:
            return tuple(
                operation
                for operation in self._retry_operations.values()
                if operation.status == "queued"
                or (
                    operation.status == "running"
                    and (now - operation.updated_at).total_seconds() >= lease_seconds
                )
            )

    async def retry_for_run(
        self, *, thread_id: str, run_id: str
    ) -> RetryOperation | None:
        async with self._lock:
            return self._retry_for_run_unlocked(thread_id=thread_id, run_id=run_id)

    def _retry_for_run_unlocked(
        self, *, thread_id: str, run_id: str
    ) -> RetryOperation | None:
        return next(
            (
                operation
                for operation in self._retry_operations.values()
                if operation.thread_id == thread_id
                and (
                    operation.source_run_id == run_id
                    or operation.target_run_id == run_id
                )
            ),
            None,
        )

    def _retry_view_for_run_unlocked(
        self, *, thread_id: str, run_id: str
    ) -> RetryOperationView | None:
        operation = self._retry_for_run_unlocked(thread_id=thread_id, run_id=run_id)
        return RetryOperationView.from_operation(operation) if operation else None

    async def _snapshot_unlocked(self, thread_id: str, run_id: str) -> WorkflowSnapshot:
        events = tuple(
            event for event in self._events.get(thread_id, ()) if event.run_id == run_id
        )
        failure = next(
            (
                event.payload.failure
                for event in reversed(events)
                if isinstance(event, ActivityEvent)
                and event.payload.activity_id == "workflow"
                and event.payload.failure is not None
            ),
            None,
        )
        record = self._run_history.get((thread_id, run_id))
        return WorkflowSnapshot(
            thread_id=thread_id,
            run_id=run_id,
            run_status=record.status if record else "unknown",
            cursor=self._cursors[thread_id],
            failure=failure,
        )

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
