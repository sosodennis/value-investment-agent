from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from src.client_debug.config import ClientDebugSettings
from src.client_debug.interface.contracts import ClientDebugEvent


class ClientDebugCaptureNotFoundError(LookupError):
    pass


class ClientDebugCaptureConflictError(ValueError):
    pass


class ClientDebugBufferFullError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClientDebugOwner:
    user_id: str
    organization_id: str


@dataclass(frozen=True, slots=True)
class ClientDebugStoredEvent:
    event: ClientDebugEvent
    received_at: datetime


@dataclass(frozen=True, slots=True)
class _StoredEventRecord:
    payload: bytes
    sequence: int
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ClientDebugAppendResult:
    accepted: tuple[ClientDebugStoredEvent, ...]
    duplicates: int
    dropped_rate_limited: int
    dropped_capacity: int

    @property
    def dropped(self) -> int:
        return self.dropped_rate_limited + self.dropped_capacity


@dataclass(slots=True)
class _Capture:
    owner: ClientDebugOwner
    expires_at: datetime
    events: OrderedDict[UUID, _StoredEventRecord]
    sequence_ids: dict[int, UUID]
    bytes_used: int


class ClientDebugBuffer:
    _EVENT_INDEX_OVERHEAD_BYTES = 512

    def __init__(
        self,
        *,
        settings: ClientDebugSettings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._captures: OrderedDict[UUID, _Capture] = OrderedDict()
        self._total_bytes = 0
        self._owner_event_times: dict[
            ClientDebugOwner, deque[tuple[datetime, int]]
        ] = {}
        self._owner_event_counts: dict[ClientDebugOwner, int] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        owner: ClientDebugOwner,
        capture_id: UUID,
        events: tuple[ClientDebugEvent, ...],
    ) -> ClientDebugAppendResult:
        now = self._now()
        with self._lock:
            self._purge(now)
            capture = self._captures.get(capture_id)
            if capture is not None and capture.owner != owner:
                raise ClientDebugCaptureNotFoundError("client debug capture not found")

            accepted_events: list[tuple[ClientDebugEvent, bytes, int]] = []
            duplicates = 0
            dropped_rate_limited = 0
            dropped_capacity = 0
            owner_event_count = self._owner_event_counts.get(owner, 0)
            pending_ids: dict[UUID, bytes] = {}
            pending_sequences: set[int] = set()
            event_count = len(capture.events) if capture is not None else 0
            bytes_used = capture.bytes_used if capture is not None else 0
            total_bytes_used = self._total_bytes
            for event in events:
                event_payload = event.model_dump_json().encode("utf-8")
                existing = capture.events.get(event.event_id) if capture else None
                if existing is not None:
                    if existing.payload != event_payload:
                        raise ClientDebugCaptureConflictError(
                            "client debug event ID was reused with different data"
                        )
                    duplicates += 1
                    continue

                pending_event = pending_ids.get(event.event_id)
                if pending_event is not None:
                    if pending_event != event_payload:
                        raise ClientDebugCaptureConflictError(
                            "client debug event ID was reused with different data"
                        )
                    duplicates += 1
                    continue

                if (
                    capture is not None and event.sequence in capture.sequence_ids
                ) or event.sequence in pending_sequences:
                    raise ClientDebugCaptureConflictError(
                        "client debug sequence was reused with different data"
                    )

                if event_count >= self._settings.max_events_per_capture:
                    dropped_capacity += 1
                    continue
                if owner_event_count >= self._settings.max_events_per_owner_per_minute:
                    dropped_rate_limited += 1
                    continue

                event_bytes = len(event_payload) + self._EVENT_INDEX_OVERHEAD_BYTES
                if (
                    bytes_used + event_bytes > self._settings.max_bytes_per_capture
                    or total_bytes_used + event_bytes > self._settings.max_total_bytes
                ):
                    dropped_capacity += 1
                    continue
                pending_ids[event.event_id] = event_payload
                pending_sequences.add(event.sequence)
                accepted_events.append((event, event_payload, event_bytes))
                event_count += 1
                bytes_used += event_bytes
                total_bytes_used += event_bytes
                owner_event_count += 1

            if capture is None:
                if not accepted_events:
                    return ClientDebugAppendResult(
                        accepted=(),
                        duplicates=duplicates,
                        dropped_rate_limited=dropped_rate_limited,
                        dropped_capacity=dropped_capacity,
                    )
                self._make_capture(owner=owner, capture_id=capture_id, now=now)
                capture = self._captures[capture_id]

            accepted: list[ClientDebugStoredEvent] = []
            for event, event_payload, event_bytes in accepted_events:
                stored = ClientDebugStoredEvent(event=event, received_at=now)
                capture.events[event.event_id] = _StoredEventRecord(
                    payload=event_payload,
                    sequence=event.sequence,
                    received_at=now,
                )
                capture.sequence_ids[event.sequence] = event.event_id
                capture.bytes_used += event_bytes
                self._total_bytes += event_bytes
                accepted.append(stored)
            if accepted_events:
                event_times = self._owner_event_times.setdefault(owner, deque())
                event_times.append((now, len(accepted_events)))
                self._owner_event_counts[owner] = owner_event_count

            return ClientDebugAppendResult(
                accepted=tuple(accepted),
                duplicates=duplicates,
                dropped_rate_limited=dropped_rate_limited,
                dropped_capacity=dropped_capacity,
            )

    def read(
        self,
        *,
        owner: ClientDebugOwner,
        capture_id: UUID,
        after_seq: int,
        limit: int,
    ) -> tuple[tuple[ClientDebugStoredEvent, ...], int, datetime]:
        now = self._now()
        with self._lock:
            self._purge(now)
            capture = self._captures.get(capture_id)
            if capture is None or capture.owner != owner:
                raise ClientDebugCaptureNotFoundError("client debug capture not found")
            events = tuple(
                sorted(
                    (
                        ClientDebugStoredEvent(
                            event=ClientDebugEvent.model_validate_json(record.payload),
                            received_at=record.received_at,
                        )
                        for record in capture.events.values()
                        if record.sequence > after_seq
                    ),
                    key=lambda stored: stored.event.sequence,
                )[:limit]
            )
            next_seq = events[-1].event.sequence if events else after_seq
            return events, next_seq, capture.expires_at

    def clear(self) -> None:
        with self._lock:
            self._captures.clear()
            self._total_bytes = 0
            self._owner_event_times.clear()
            self._owner_event_counts.clear()

    def _make_capture(
        self,
        *,
        owner: ClientDebugOwner,
        capture_id: UUID,
        now: datetime,
    ) -> None:
        if len(self._captures) >= self._settings.max_captures:
            raise ClientDebugBufferFullError("client debug capture buffer is full")
        owner_captures = sum(
            1 for capture in self._captures.values() if capture.owner == owner
        )
        if owner_captures >= self._settings.max_captures_per_owner:
            raise ClientDebugBufferFullError("client debug owner capture limit reached")
        self._captures[capture_id] = _Capture(
            owner=owner,
            expires_at=now + timedelta(seconds=self._settings.ttl_seconds),
            events=OrderedDict(),
            sequence_ids={},
            bytes_used=0,
        )

    def _remove_capture(self, capture_id: UUID) -> None:
        capture = self._captures.pop(capture_id, None)
        if capture is not None:
            self._total_bytes -= capture.bytes_used

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    def _purge(self, now: datetime) -> None:
        expired = [
            capture_id
            for capture_id, capture in self._captures.items()
            if capture.expires_at <= now
        ]
        for capture_id in expired:
            capture = self._captures.pop(capture_id)
            self._total_bytes -= capture.bytes_used
        cutoff = now - timedelta(seconds=60)
        for owner, event_times in list(self._owner_event_times.items()):
            while event_times and event_times[0][0] <= cutoff:
                _, count = event_times.popleft()
                self._owner_event_counts[owner] -= count
            if not event_times:
                del self._owner_event_times[owner]
                del self._owner_event_counts[owner]
