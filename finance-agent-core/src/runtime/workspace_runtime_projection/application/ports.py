from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeCursorRecord,
    WorkspaceRuntimeRunStatusRecord,
)


class WorkspaceRuntimeProjectionRepository(Protocol):
    async def append_activity_event(
        self,
        record: WorkspaceRuntimeActivityRecord,
    ) -> None: ...

    async def fetch_recent_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> list[WorkspaceRuntimeActivityRecord]: ...

    async def fetch_activity_since(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int = 200,
    ) -> list[WorkspaceRuntimeActivityRecord]: ...

    async def fetch_latest_activity_segment_by_node(
        self,
        *,
        thread_id: str,
        agent_id: str,
        run_id: str,
        node: str,
    ) -> WorkspaceRuntimeActivitySegmentRecord | None: ...

    async def fetch_activity_segments(
        self,
        *,
        thread_id: str,
        agent_id: str,
        limit: int = 5,
        before_updated_at: datetime | None = None,
    ) -> list[WorkspaceRuntimeActivitySegmentRecord]: ...

    async def fetch_latest_cursor(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeCursorRecord | None: ...

    async def fetch_latest_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]: ...

    async def fetch_latest_lifecycle_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]: ...

    async def append_activity_segment(
        self,
        record: WorkspaceRuntimeActivitySegmentRecord,
    ) -> None: ...

    async def update_activity_segment(
        self,
        record: WorkspaceRuntimeActivitySegmentRecord,
    ) -> None: ...

    async def close_open_segments_for_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: str,
        closed_at: datetime,
    ) -> None: ...

    async def fetch_run_status(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeRunStatusRecord | None: ...

    async def upsert_run_status(
        self,
        record: WorkspaceRuntimeRunStatusRecord,
    ) -> None: ...

    async def upsert_cursor(
        self,
        *,
        thread_id: str,
        last_seq_id: int,
    ) -> WorkspaceRuntimeCursorRecord: ...
