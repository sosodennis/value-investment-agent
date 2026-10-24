from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from src.analysis_runtime.domain.contracts import (
    ActivityEvent,
    ActivitySnapshot,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    InvalidCursorError,
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
        self._retention = replay_retention

    async def append_atomic(self, event: ActivityEvent) -> bool:
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
                page[-1].seq_id
                if page
                else (self._cursors[thread_id] if events else after_seq)
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
            return record
