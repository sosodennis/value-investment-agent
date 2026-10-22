from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from time import perf_counter

from .errors import (
    ServiceError,
    cancelled,
    deadline_exceeded,
    inference_failed,
    model_not_ready,
    overloaded,
    unavailable,
)
from .models import InferenceRunner, ModelStatus
from .telemetry import IN_FLIGHT, INFERENCE_TIME, QUEUE_SIZE, QUEUE_WAIT

logger = logging.getLogger("uvicorn.error")


@dataclass
class _WorkItem:
    payload: object
    deadline: float
    accepted_at: float
    request_id: str
    future: asyncio.Future[dict[str, object]]
    cancelled: bool = False


class OperationRuntime:
    def __init__(
        self,
        *,
        runner: InferenceRunner,
        max_in_flight: int,
        queue_depth: int,
    ) -> None:
        self.runner = runner
        self.max_in_flight = max_in_flight
        self.queue_depth = queue_depth
        self._queue: deque[_WorkItem] = deque()
        self._condition = asyncio.Condition()
        self._workers: list[asyncio.Task[None]] = []
        self._accepting = False
        self._ready = False
        self._status: ModelStatus | None = None
        self._stopping = False
        self._in_flight = 0

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def model_revision(self) -> str:
        return self.runner.model_revision

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def status(self) -> ModelStatus | None:
        return self._status

    async def start(self) -> ModelStatus:
        self._status = await asyncio.to_thread(self.runner.load)
        if self._status.loaded:
            try:
                await asyncio.to_thread(self.runner.warmup)
            except Exception as exc:
                self._status = ModelStatus(
                    False,
                    self.runner.model_revision,
                    f"model warmup failed: {exc}",
                )
        self._ready = self._status.loaded
        self._accepting = self._status.loaded
        self._workers = [
            asyncio.create_task(
                self._worker(), name=f"inference-{self.runner.operation}-{i}"
            )
            for i in range(self.max_in_flight)
        ]
        return self._status

    async def submit(
        self,
        payload: object,
        *,
        deadline_ms: int,
        request_id: str = "",
    ) -> dict[str, object]:
        try:
            result = await self._submit(
                payload, deadline_ms=deadline_ms, request_id=request_id
            )
        except ServiceError as exc:
            self._log_request(
                request_id, exc.code, queue_wait_ms=None, inference_ms=None
            )
            raise
        return result

    async def _submit(
        self, payload: object, *, deadline_ms: int, request_id: str
    ) -> dict[str, object]:
        if not self._ready:
            raise model_not_ready()
        if not self._accepting:
            raise unavailable("inference service is draining")

        loop = asyncio.get_running_loop()
        item = _WorkItem(
            payload=payload,
            deadline=loop.time() + deadline_ms / 1000.0,
            accepted_at=loop.time(),
            request_id=request_id,
            future=loop.create_future(),
        )
        async with self._condition:
            if len(self._queue) >= self.queue_depth:
                raise overloaded()
            self._queue.append(item)
            QUEUE_SIZE.labels(self.runner.operation, self.model_revision).set(
                len(self._queue)
            )
            self._condition.notify()
        remaining = item.deadline - loop.time()
        if remaining <= 0:
            await self._cancel_item(item)
            raise deadline_exceeded()
        try:
            return await asyncio.wait_for(
                asyncio.shield(item.future), timeout=remaining
            )
        except TimeoutError as exc:
            await self._cancel_item(item)
            raise deadline_exceeded() from exc
        except asyncio.CancelledError as exc:
            await self._cancel_item(item)
            raise cancelled() from exc

    async def stop(self, *, grace_seconds: float) -> None:
        self._accepting = False
        self._stopping = True
        async with self._condition:
            while self._queue:
                item = self._queue.popleft()
                item.cancelled = True
                if not item.future.done():
                    item.future.set_exception(unavailable("service is shutting down"))
            QUEUE_SIZE.labels(self.runner.operation, self.model_revision).set(0)
            self._condition.notify_all()
        if not self._workers:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._workers, return_exceptions=True),
                timeout=grace_seconds,
            )
        except TimeoutError:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)

    async def _cancel_item(self, item: _WorkItem) -> None:
        async with self._condition:
            item.cancelled = True
            try:
                self._queue.remove(item)
            except ValueError:
                pass
            else:
                queue_wait = max(
                    0.0, asyncio.get_running_loop().time() - item.accepted_at
                )
                QUEUE_WAIT.labels(self.runner.operation, self.model_revision).observe(
                    queue_wait
                )
                QUEUE_SIZE.labels(self.runner.operation, self.model_revision).set(
                    len(self._queue)
                )
            if not item.future.done():
                item.future.cancel()
            self._condition.notify()

    async def _next_item(self) -> _WorkItem | None:
        async with self._condition:
            while not self._queue and not self._stopping:
                await self._condition.wait()
            if not self._queue:
                return None
            return self._queue.popleft()

    async def _worker(self) -> None:
        while True:
            item = await self._next_item()
            if item is None:
                return
            queue_wait = max(0.0, asyncio.get_running_loop().time() - item.accepted_at)
            QUEUE_WAIT.labels(self.runner.operation, self.model_revision).observe(
                queue_wait
            )
            QUEUE_SIZE.labels(self.runner.operation, self.model_revision).set(
                len(self._queue)
            )
            if item.cancelled or item.future.cancelled():
                continue
            if asyncio.get_running_loop().time() >= item.deadline:
                if not item.future.done():
                    item.future.set_exception(deadline_exceeded())
                continue
            self._in_flight += 1
            IN_FLIGHT.labels(self.runner.operation, self.model_revision).inc()
            started = perf_counter()
            outcome = "SUCCESS"
            try:
                result = await asyncio.to_thread(self.runner.infer, item.payload)
                if item.cancelled:
                    outcome = "CANCELLED"
                elif asyncio.get_running_loop().time() >= item.deadline:
                    outcome = "DEADLINE_EXCEEDED"
                    if not item.future.done():
                        item.future.set_exception(deadline_exceeded())
                elif not item.future.done():
                    item.future.set_result(result)
            except Exception as exc:
                outcome = "INFERENCE_FAILED"
                if not item.future.done():
                    item.future.set_exception(inference_failed())
                _ = exc
            finally:
                inference_seconds = perf_counter() - started
                INFERENCE_TIME.labels(
                    self.runner.operation, self.model_revision
                ).observe(inference_seconds)
                self._in_flight -= 1
                IN_FLIGHT.labels(self.runner.operation, self.model_revision).dec()
                self._log_request(
                    item.request_id,
                    outcome,
                    queue_wait_ms=queue_wait * 1000,
                    inference_ms=inference_seconds * 1000,
                )

    def _log_request(
        self,
        request_id: str,
        outcome: str,
        *,
        queue_wait_ms: float | None,
        inference_ms: float | None,
    ) -> None:
        logger.info(
            json.dumps(
                {
                    "event": "model_inference_request",
                    "request_id": request_id,
                    "operation": self.runner.operation,
                    "model_revision": self.model_revision,
                    "outcome": outcome,
                    "queue_wait_ms": queue_wait_ms,
                    "inference_ms": inference_ms,
                    "in_flight": self._in_flight,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
