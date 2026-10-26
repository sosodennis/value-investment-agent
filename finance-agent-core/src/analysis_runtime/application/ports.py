from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Protocol

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivitySnapshot,
    AnalysisRunPage,
    AnalysisRunRecord,
    ReplayPage,
    RunStatus,
    RunStatusRecord,
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
    async def append_atomic(self, event: ActivityEvent) -> bool: ...

    async def replay(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int,
    ) -> ReplayPage: ...

    async def snapshot(self, *, thread_id: str, run_id: str) -> ActivitySnapshot: ...

    async def get_run(self, *, thread_id: str) -> RunStatusRecord | None: ...

    async def get_run_history(
        self, *, principal_id: str, thread_id: str, run_id: str
    ) -> AnalysisRunRecord | None: ...

    async def list_run_history(
        self,
        *,
        principal_id: str,
        limit: int,
        before_started_at: datetime | None = None,
        before_thread_id: str | None = None,
        before_run_id: str | None = None,
    ) -> AnalysisRunPage: ...

    async def set_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: RunStatus,
        now: datetime,
        principal_id: str | None = None,
        input_data: Mapping[str, object] | None = None,
    ) -> RunStatusRecord: ...


class RuntimeSubscriber(Protocol):
    async def receive(self) -> ActivityEvent | None: ...

    def close(self) -> None: ...


class NotificationHub(Protocol):
    async def publish(self, event: ActivityEvent) -> None: ...


class LlmProviderClientPort(Protocol):
    async def complete(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class InferenceClientPort(Protocol):
    async def infer(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class SearchClientPort(Protocol):
    async def search(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
