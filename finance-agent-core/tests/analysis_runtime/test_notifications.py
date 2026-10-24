from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from src.analysis_runtime.domain.contracts import Activity, ActivityEvent
from src.analysis_runtime.infrastructure.notifications import (
    PostgresNotificationHub,
)


class FakeNotificationBus:
    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []

    def connect(self) -> FakeConnection:
        connection = FakeConnection(self)
        self.connections.append(connection)
        return connection

    def notify(self, channel: str, payload: str) -> None:
        for connection in tuple(self.connections):
            connection.emit(channel, payload)


class FakeConnection:
    def __init__(self, bus: FakeNotificationBus) -> None:
        self.bus = bus
        self.listeners: dict[str, list[Callable[..., Any]]] = {}
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def add_listener(self, channel: str, callback: Callable[..., Any]) -> None:
        self.listeners.setdefault(channel, []).append(callback)

    async def remove_listener(self, channel: str, callback: Callable[..., Any]) -> None:
        self.listeners[channel].remove(callback)

    async def execute(self, _query: str, channel: str, payload: str) -> str:
        self.bus.notify(channel, payload)
        return "SELECT 1"

    def emit(self, channel: str, payload: str) -> None:
        for callback in self.listeners.get(channel, ()):
            callback(self, 1, channel, payload)

    async def close(self) -> None:
        self.closed = True


def _event(*, thread_id: str = "thread-1", seq_id: int = 1) -> ActivityEvent:
    activity = Activity(
        activity_id="workflow",
        thread_id=thread_id,
        run_id="run-1",
        scope_path=("workflow",),
        kind="phase",
        status="running",
        label="Workflow running",
        attempt=1,
    )
    return ActivityEvent(
        event_id=f"event-{seq_id}",
        seq_id=seq_id,
        thread_id=thread_id,
        run_id="run-1",
        occurred_at="2026-10-25T00:00:00Z",
        payload=activity,
    )


@pytest.mark.asyncio
async def test_postgres_hubs_fan_out_to_subscribers_in_each_worker() -> None:
    bus = FakeNotificationBus()
    first = PostgresNotificationHub(connect=lambda _dsn: _connected(bus))
    second = PostgresNotificationHub(connect=lambda _dsn: _connected(bus))
    await first.start()
    await second.start()
    first_subscriber = await first.subscribe(thread_id="thread-1")
    second_subscriber = await second.subscribe(thread_id="thread-1")

    event = _event()
    await first.publish(event)

    assert await asyncio.wait_for(first_subscriber.receive(), timeout=0.5) == event
    assert await asyncio.wait_for(second_subscriber.receive(), timeout=0.5) == event

    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_postgres_hub_ignores_malformed_notifications_and_closes_subscribers() -> (
    None
):
    bus = FakeNotificationBus()
    hub = PostgresNotificationHub(connect=lambda _dsn: _connected(bus))
    await hub.start()
    subscriber = await hub.subscribe(thread_id="thread-1")

    connection = bus.connections[0]
    connection.emit("workflow_activity", "not-json")
    await asyncio.sleep(0)
    assert subscriber._queue.empty()

    await hub.close()
    assert await asyncio.wait_for(subscriber.receive(), timeout=0.5) is None


async def _connected(bus: FakeNotificationBus) -> FakeConnection:
    return bus.connect()
