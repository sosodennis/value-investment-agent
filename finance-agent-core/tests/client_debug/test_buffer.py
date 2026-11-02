from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.client_debug.config import ClientDebugSettings
from src.client_debug.infrastructure.runtime_buffer import (
    ClientDebugBuffer,
    ClientDebugCaptureNotFoundError,
    ClientDebugOwner,
)
from src.client_debug.interface.contracts import (
    ClientDebugContext,
    ClientDebugEvent,
    ClientDebugViewport,
)


def _event(event_id: UUID | None = None, sequence: int = 1) -> ClientDebugEvent:
    return ClientDebugEvent(
        event_id=event_id or uuid4(),
        sequence=sequence,
        occurred_at=datetime(2026, 11, 2, tzinfo=UTC),
        elapsed_ms=float(sequence),
        name="ui.layout",
        context=ClientDebugContext(
            route="/workspace",
            viewport=ClientDebugViewport(width=1200, height=800, dpr=2),
        ),
        details={"rect": {"width": 100, "height": 40}},
    )


def test_runtime_buffer_deduplicates_and_scopes_captures() -> None:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True, max_events_per_capture=2, max_captures=2
        ),
        clock=lambda: now,
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    capture_id = uuid4()
    first = _event(sequence=1)
    second = _event(sequence=2)

    result = buffer.append(owner=owner, capture_id=capture_id, events=(first, second))
    duplicate = buffer.append(owner=owner, capture_id=capture_id, events=(first,))

    assert len(result.accepted) == 2
    assert duplicate.duplicates == 1
    assert (
        buffer.read(owner=owner, capture_id=capture_id, after_seq=0, limit=10)[1] == 2
    )

    with pytest.raises(ClientDebugCaptureNotFoundError):
        buffer.read(
            owner=ClientDebugOwner(user_id="other", organization_id="org-1"),
            capture_id=capture_id,
            after_seq=0,
            limit=10,
        )


def test_runtime_buffer_expires_without_persistence() -> None:
    current = [datetime(2026, 11, 2, tzinfo=UTC)]
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(enabled=True, ttl_seconds=60),
        clock=lambda: current[0],
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    capture_id = uuid4()
    buffer.append(owner=owner, capture_id=capture_id, events=(_event(),))

    current[0] += timedelta(seconds=61)
    with pytest.raises(ClientDebugCaptureNotFoundError):
        buffer.read(owner=owner, capture_id=capture_id, after_seq=0, limit=10)


def test_runtime_buffer_rejects_conflicting_batch_atomically() -> None:
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(enabled=True),
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    capture_id = uuid4()
    first = _event(sequence=1)
    buffer.append(owner=owner, capture_id=capture_id, events=(first,))

    with pytest.raises(ValueError):
        buffer.append(
            owner=owner,
            capture_id=capture_id,
            events=(_event(sequence=2), _event(sequence=1)),
        )

    events, _, _ = buffer.read(
        owner=owner, capture_id=capture_id, after_seq=0, limit=10
    )
    assert [stored.event.sequence for stored in events] == [1]


def test_runtime_buffer_enforces_bytes_and_owner_capture_limits() -> None:
    byte_settings = ClientDebugSettings(
        enabled=True,
        max_bytes_per_capture=100,
        max_total_bytes=700,
    )
    buffer = ClientDebugBuffer(settings=byte_settings)
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    first_capture = uuid4()
    result = buffer.append(
        owner=owner, capture_id=first_capture, events=(_event(sequence=1),)
    )
    assert result.accepted == ()
    assert result.dropped == 1
    assert result.dropped_capacity == 1
    assert result.dropped_rate_limited == 0

    owner_settings = ClientDebugSettings(
        enabled=True,
        max_bytes_per_capture=10_000,
        max_total_bytes=20_000,
        max_captures=4,
        max_captures_per_owner=1,
    )
    owner_buffer = ClientDebugBuffer(settings=owner_settings)
    second_capture = uuid4()
    accepted = owner_buffer.append(
        owner=owner, capture_id=second_capture, events=(_event(sequence=2),)
    )
    assert len(accepted.accepted) == 1

    with pytest.raises(RuntimeError):
        owner_buffer.append(
            owner=owner, capture_id=uuid4(), events=(_event(sequence=3),)
        )


def test_runtime_buffer_accounts_for_retained_event_indexes() -> None:
    event = _event()
    serialized_size = len(event.model_dump_json().encode("utf-8"))
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    settings = ClientDebugSettings(
        enabled=True,
        max_bytes_per_capture=serialized_size + 511,
        max_total_bytes=serialized_size + 511,
    )
    buffer = ClientDebugBuffer(settings=settings)

    result = buffer.append(owner=owner, capture_id=uuid4(), events=(event,))

    assert result.accepted == ()
    assert result.dropped == 1


def test_runtime_buffer_accounts_for_pending_batch_bytes() -> None:
    event = _event(sequence=1)
    event_bytes = len(event.model_dump_json().encode("utf-8")) + 512
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_bytes_per_capture=event_bytes * 2,
            max_total_bytes=event_bytes * 2 - 1,
        )
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")

    result = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(event, _event(sequence=2)),
    )

    assert len(result.accepted) == 1
    assert result.dropped_capacity == 1


def test_runtime_buffer_rate_limits_owner_events() -> None:
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_events_per_owner_per_minute=1,
            max_bytes_per_capture=10_000,
        )
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    first = buffer.append(owner=owner, capture_id=uuid4(), events=(_event(sequence=1),))
    second = buffer.append(
        owner=owner, capture_id=uuid4(), events=(_event(sequence=2),)
    )

    assert len(first.accepted) == 1
    assert second.accepted == ()
    assert second.dropped == 1
    assert second.dropped_rate_limited == 1
    assert second.dropped_capacity == 0


def test_runtime_buffer_rate_limit_reopens_after_one_minute() -> None:
    current = [datetime(2026, 11, 2, tzinfo=UTC)]
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_events_per_owner_per_minute=2,
            max_bytes_per_capture=10_000,
        ),
        clock=lambda: current[0],
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")

    first = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=1), _event(sequence=2)),
    )
    blocked = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=3),),
    )
    current[0] += timedelta(seconds=60, microseconds=1)
    reopened = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=4),),
    )

    assert len(first.accepted) == 2
    assert blocked.dropped == 1
    assert len(reopened.accepted) == 1


def test_runtime_buffer_counts_each_batch_once_in_rate_window() -> None:
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_events_per_owner_per_minute=3,
            max_bytes_per_capture=10_000,
        )
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    first = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=1), _event(sequence=2)),
    )
    second = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=3),),
    )

    assert len(first.accepted) == 2
    assert len(second.accepted) == 1
    assert second.dropped == 0


def test_runtime_buffer_allows_eight_sixty_fps_samplers_inside_rate_window() -> None:
    samples = 8 * 60 * 60
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_events_per_capture=samples + 1,
            max_bytes_per_capture=64 * 1024 * 1024,
            max_total_bytes=64 * 1024 * 1024,
        )
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    capture_id = uuid4()
    events = tuple(_event(sequence=index) for index in range(1, samples + 1))

    result = buffer.append(owner=owner, capture_id=capture_id, events=events)

    assert len(result.accepted) == samples
    assert result.dropped == 0


def test_runtime_buffer_reports_capture_capacity_before_rate_limit() -> None:
    buffer = ClientDebugBuffer(
        settings=ClientDebugSettings(
            enabled=True,
            max_events_per_owner_per_minute=10_000,
            max_events_per_capture=2,
            max_bytes_per_capture=64 * 1024,
        )
    )
    owner = ClientDebugOwner(user_id="user-1", organization_id="org-1")
    result = buffer.append(
        owner=owner,
        capture_id=uuid4(),
        events=(_event(sequence=1), _event(sequence=2), _event(sequence=3)),
    )

    assert len(result.accepted) == 2
    assert result.dropped_capacity == 1
    assert result.dropped_rate_limited == 0
