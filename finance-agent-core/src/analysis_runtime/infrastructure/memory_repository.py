from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from src.analysis_runtime.domain.contracts import (
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


class InMemoryActivityRepository:
    """Deterministic repository used by tests and local composition."""

    def __init__(self, *, replay_retention: int = 10_000) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, list[ActivityEvent]] = defaultdict(list)
        self._event_ids: dict[str, set[str]] = defaultdict(set)
        self._cursors: dict[str, int] = defaultdict(int)
        self._runs: dict[str, RunStatusRecord] = {}
        self._pending_resumes: dict[str, PendingResume] = {}
        self._retention = replay_retention

    async def append_atomic(
        self, event: ActivityEvent, *, run_status: RunStatus | None = None
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

    async def snapshot(self, *, thread_id: str, run_id: str) -> ActivitySnapshot:
        async with self._lock:
            events = tuple(self._events.get(thread_id, ()))
            latest: dict[str, ActivityEvent] = {}
            for event in events:
                if event.run_id == run_id:
                    latest[event.payload.activity_id] = event
            active_statuses = {"queued", "running", "waiting"}
            active = tuple(
                event.payload
                for event in latest.values()
                if event.payload.status in active_statuses
            )
            recent = tuple(
                event.payload for event in reversed(events) if event.run_id == run_id
            )[:50]
            run = self._runs.get(thread_id)
            status: RunStatus = run.status if run else "queued"
            return ActivitySnapshot(
                thread_id=thread_id,
                run_id=run_id,
                run_status=status,
                cursor=self._cursors[thread_id],
                active_activities=active,
                recent_activities=recent,
            )

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None:
        async with self._lock:
            return self._runs.get(thread_id)

    async def set_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: RunStatus,
        now: datetime,
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
            return record

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
    ):
        async with self._lock:
            run = self._runs.get(thread_id)
            if run is None or run.run_id != run_id:
                raise InteractionNotAvailableError("run cannot accept this interaction")
            if run.status != "waiting":
                raise InteractionNotAvailableError("run is not waiting for input")

            event = next(
                (
                    item
                    for item in reversed(self._events.get(thread_id, ()))
                    if item.run_id == run_id and item.payload.activity_id == activity_id
                ),
                None,
            )
            activity = event.payload if event is not None else None
            if (
                activity is None
                or activity.status != "waiting"
                or activity.interruption is None
                or activity.interruption.interaction_id != interaction_id
            ):
                raise InteractionNotAvailableError(
                    "interaction is stale or unavailable"
                )
            candidates = activity.interruption.request.candidates
            if response.selected_symbol not in {item.symbol for item in candidates}:
                raise InvalidInteractionResponseError(
                    "selected symbol is not one of the available candidates"
                )

            self._runs[thread_id] = run.model_copy(
                update={"status": "running", "updated_at": now, "ended_at": None}
            )
            self._pending_resumes[thread_id] = PendingResume(
                thread_id=thread_id,
                run_id=run_id,
                principal_id=principal_id,
                activity=activity.interruption,
                activity_id=activity.activity_id,
                scope_path=activity.scope_path,
                attempt=activity.attempt,
                response=response,
            )
            return activity

    async def pending_resumes(self) -> tuple[PendingResume, ...]:
        async with self._lock:
            return tuple(self._pending_resumes.values())
