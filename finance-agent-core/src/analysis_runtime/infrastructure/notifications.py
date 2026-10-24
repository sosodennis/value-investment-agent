from __future__ import annotations

import asyncio

from src.analysis_runtime.domain.contracts import ActivityEvent
from src.analysis_runtime.domain.errors import SubscriberOverloadedError


class QueueSubscriber:
    def __init__(self, *, thread_id: str, maxsize: int) -> None:
        self.thread_id = thread_id
        self._queue: asyncio.Queue[ActivityEvent | None] = asyncio.Queue(
            maxsize=maxsize
        )
        self._closed = False

    def push(self, event: ActivityEvent) -> None:
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

    async def receive(self) -> ActivityEvent | None:
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

    async def publish(self, event: ActivityEvent) -> None:
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
