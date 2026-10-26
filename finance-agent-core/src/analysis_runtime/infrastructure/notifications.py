from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import timezone
from typing import Any

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.analysis_runtime.domain.contracts import WorkflowEvent
from src.analysis_runtime.domain.errors import SubscriberOverloadedError

logger = logging.getLogger(__name__)
_EVENT_ADAPTER = TypeAdapter(WorkflowEvent)


class _EventPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    seq_id: int = Field(ge=1)


class QueueSubscriber:
    def __init__(self, *, thread_id: str, maxsize: int) -> None:
        self.thread_id = thread_id
        self._queue: asyncio.Queue[WorkflowEvent | None] = asyncio.Queue(
            maxsize=maxsize
        )
        self._closed = False

    def push(self, event: WorkflowEvent) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            self._closed = True
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            raise SubscriberOverloadedError("subscriber queue is full") from exc

    async def receive(self) -> WorkflowEvent | None:
        return await self._queue.get()

    def close(self) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


class BoundedNotificationHub:
    def __init__(self, *, queue_size: int = 128) -> None:
        self._queue_size = queue_size
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, set[QueueSubscriber]] = {}

    async def subscribe(self, *, thread_id: str) -> QueueSubscriber:
        subscriber = QueueSubscriber(thread_id=thread_id, maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.setdefault(thread_id, set()).add(subscriber)
        return subscriber

    async def unsubscribe(self, subscriber: QueueSubscriber) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(subscriber.thread_id)
            if subscribers is not None:
                subscribers.discard(subscriber)
                if not subscribers:
                    self._subscribers.pop(subscriber.thread_id, None)
        subscriber.close()

    async def publish(self, event: WorkflowEvent) -> None:
        await self._dispatch(event)

    async def _dispatch(self, event: WorkflowEvent) -> None:
        overloaded: list[QueueSubscriber] = []
        async with self._lock:
            subscribers = self._subscribers.get(event.thread_id, set())
            for subscriber in tuple(subscribers):
                try:
                    subscriber.push(event)
                except SubscriberOverloadedError:
                    overloaded.append(subscriber)
            for subscriber in overloaded:
                subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(event.thread_id, None)

    async def close(self) -> None:
        async with self._lock:
            subscribers = [
                subscriber
                for thread_subscribers in self._subscribers.values()
                for subscriber in thread_subscribers
            ]
            self._subscribers.clear()
        for subscriber in subscribers:
            subscriber.close()


class PostgresNotificationHub(BoundedNotificationHub):
    """Cross-worker activity fan-out backed by PostgreSQL LISTEN/NOTIFY.

    The event repository remains the durable source of truth. PostgreSQL
    notifications carry only an event pointer; receiving workers load the
    committed event before waking their subscribers.
    """

    def __init__(
        self,
        *,
        dsn: str | None = None,
        channel: str = "workflow_activity",
        queue_size: int = 128,
        max_payload_bytes: int = 7900,
        connect: Callable[..., Awaitable[Any]] | None = None,
        load_event: Callable[[str], Awaitable[WorkflowEvent | None]] | None = None,
    ) -> None:
        super().__init__(queue_size=queue_size)
        self._dsn = dsn or _default_postgres_dsn()
        self._channel = channel
        self._max_payload_bytes = max_payload_bytes
        self._connect = connect or asyncpg.connect
        self._load_event = load_event or _load_committed_event
        self._connection: Any | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._connection is not None and not self._connection.is_closed():
                return
            connection = await self._connect(self._dsn)
            await connection.add_listener(self._channel, self._on_notification)
            self._connection = connection

    async def publish(self, event: WorkflowEvent) -> None:
        connection = self._connection
        if connection is None or connection.is_closed():
            logger.warning(
                "workflow activity notification connection unavailable",
                extra={"thread_id": event.thread_id, "seq_id": event.seq_id},
            )
            return
        payload = json.dumps(
            _EventPointer(
                event_id=event.event_id,
                thread_id=event.thread_id,
                seq_id=event.seq_id,
            ).model_dump(),
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > self._max_payload_bytes:
            logger.warning(
                "workflow activity notification payload exceeds limit",
                extra={"thread_id": event.thread_id, "seq_id": event.seq_id},
            )
            return
        try:
            await connection.execute("SELECT pg_notify($1, $2)", self._channel, payload)
        except (asyncpg.PostgresError, OSError):
            # The event is already durable. A later replay from its cursor will
            # recover it when the notification connection is unavailable.
            logger.warning(
                "workflow activity notification failed",
                extra={"thread_id": event.thread_id, "seq_id": event.seq_id},
                exc_info=True,
            )

    def _on_notification(
        self, _connection: Any, _pid: int, _channel: str, payload: str
    ) -> None:
        asyncio.create_task(self._dispatch_payload(payload))

    async def _dispatch_payload(self, payload: str) -> None:
        try:
            pointer = _EventPointer.model_validate(json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("invalid workflow event notification ignored")
            return
        try:
            event = await self._load_event(pointer.event_id)
            if event is None or (event.thread_id, event.seq_id) != (
                pointer.thread_id,
                pointer.seq_id,
            ):
                return
            event = _EVENT_ADAPTER.validate_python(event)
        except (asyncpg.PostgresError, OSError, TypeError, ValueError):
            logger.warning("workflow event notification lookup failed", exc_info=True)
            return
        await self._dispatch(event)

    async def close(self) -> None:
        async with self._lifecycle_lock:
            connection = self._connection
            self._connection = None
            if connection is not None and not connection.is_closed():
                try:
                    await connection.remove_listener(
                        self._channel, self._on_notification
                    )
                except (asyncpg.PostgresError, OSError):
                    logger.debug(
                        "workflow activity listener removal failed", exc_info=True
                    )
                try:
                    await connection.close()
                except (asyncpg.PostgresError, OSError):
                    logger.debug(
                        "workflow activity notification close failed", exc_info=True
                    )
        await super().close()


async def _load_committed_event(event_id: str) -> WorkflowEvent | None:
    from sqlalchemy import select

    from src.infrastructure.database import AsyncSessionLocal
    from src.infrastructure.models import WorkflowActivityEvent

    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(WorkflowActivityEvent).where(
                WorkflowActivityEvent.event_id == event_id
            )
        )
    if row is None:
        return None
    return _EVENT_ADAPTER.validate_python(
        {
            "event_id": row.event_id,
            "thread_id": row.thread_id,
            "run_id": row.run_id,
            "seq_id": row.seq_id,
            "event_version": row.event_version,
            "event_name": row.event_name,
            "occurred_at": row.occurred_at.replace(tzinfo=timezone.utc),
            "payload": row.payload,
        }
    )


def _default_postgres_dsn() -> str:
    from src.infrastructure.database import DATABASE_URL

    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
