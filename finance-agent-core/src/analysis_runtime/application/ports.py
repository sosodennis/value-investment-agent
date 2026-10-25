from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Protocol

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivitySnapshot,
    PendingResume,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
    TickerSelectionResponse,
)


class GraphRunner(Protocol):
    async def run(
        self,
        *,
        thread_id: str,
        run_id: str,
        input_data: Mapping[str, object],
        principal_id: str,
    ) -> AsyncIterator[Activity | Mapping[str, object]]: ...


class OwnerPort(Protocol):
    async def owns(self, *, principal_id: str, thread_id: str) -> bool: ...

    async def claim(self, *, principal_id: str, thread_id: str) -> bool: ...


class ActivityRepository(Protocol):
    async def append_atomic(
        self, event: ActivityEvent, *, run_status: RunStatus | None = None
    ) -> bool: ...

    async def replay(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int,
    ) -> ReplayPage: ...

    async def snapshot(self, *, thread_id: str, run_id: str) -> ActivitySnapshot: ...

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None: ...

    async def set_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: RunStatus,
        now: datetime,
    ) -> RunStatusRecord: ...

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
    ) -> Activity: ...

    async def pending_resumes(self) -> tuple[PendingResume, ...]: ...


class RuntimeSubscriber(Protocol):
    async def receive(self) -> ActivityEvent | None: ...

    def close(self) -> None: ...


class NotificationHub(Protocol):
    async def subscribe(self, *, thread_id: str) -> RuntimeSubscriber: ...

    async def unsubscribe(self, subscriber: RuntimeSubscriber) -> None: ...

    async def publish(self, event: ActivityEvent) -> None: ...

    async def close(self) -> None: ...


class LlmProviderClientPort(Protocol):
    async def complete(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class InferenceClientPort(Protocol):
    async def infer(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class SearchClientPort(Protocol):
    async def search(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
