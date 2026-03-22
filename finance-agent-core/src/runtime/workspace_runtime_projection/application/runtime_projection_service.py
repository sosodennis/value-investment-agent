from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from src.interface.events.protocol import AgentEvent
from src.runtime.workspace_runtime_projection.application.ports import (
    WorkspaceRuntimeProjectionRepository,
)
from src.runtime.workspace_runtime_projection.domain import (
    project_activity_segment,
    project_run_status,
)
from src.runtime.workspace_runtime_projection.domain.contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeCursorRecord,
    WorkspaceRuntimeRunStatusRecord,
)
from src.shared.kernel.types import JSONObject

_ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent.status",
        "agent.lifecycle",
        "state.update",
        "interrupt.request",
        "lifecycle.status",
        "error",
        "content.delta",
    }
)


@dataclass(frozen=True)
class WorkspaceRuntimeProjectionService:
    repository: WorkspaceRuntimeProjectionRepository

    async def record_event(self, event: AgentEvent) -> None:
        if event.type not in _ALLOWED_EVENT_TYPES:
            return

        if event.type == "content.delta":
            await self._update_cursor(thread_id=event.thread_id, seq_id=event.seq_id)
            return

        record = self._build_activity_record(event)
        if event.type == "agent.status" and record.run_id is None:
            await self._update_cursor(thread_id=event.thread_id, seq_id=event.seq_id)
            return
        try:
            await self.repository.append_activity_event(record)
        except IntegrityError:
            # Idempotent replays can hit the unique thread_id + seq_id constraint.
            pass

        if event.type == "agent.status":
            await self._update_activity_segments(record)
        if event.type in {"lifecycle.status", "interrupt.request", "error"}:
            await self._update_run_status(record)

        await self._update_cursor(thread_id=event.thread_id, seq_id=event.seq_id)

    async def fetch_recent_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> tuple[WorkspaceRuntimeActivityRecord, ...]:
        records = await self.repository.fetch_recent_activity(
            thread_id=thread_id,
            limit=limit,
        )
        return tuple(records)

    async def fetch_activity_since(
        self,
        *,
        thread_id: str,
        after_seq: int,
        limit: int = 200,
    ) -> tuple[WorkspaceRuntimeActivityRecord, ...]:
        records = await self.repository.fetch_activity_since(
            thread_id=thread_id,
            after_seq=after_seq,
            limit=limit,
        )
        return tuple(records)

    async def fetch_activity_segments(
        self,
        *,
        thread_id: str,
        agent_id: str,
        limit: int = 5,
        before_updated_at: datetime | None = None,
    ) -> tuple[WorkspaceRuntimeActivitySegmentRecord, ...]:
        records = await self.repository.fetch_activity_segments(
            thread_id=thread_id,
            agent_id=agent_id,
            limit=limit,
            before_updated_at=before_updated_at,
        )
        return tuple(records)

    async def fetch_cursor(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeCursorRecord | None:
        return await self.repository.fetch_latest_cursor(thread_id=thread_id)

    async def fetch_latest_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]:
        return await self.repository.fetch_latest_statuses(thread_id=thread_id)

    async def fetch_latest_lifecycle_statuses(
        self,
        *,
        thread_id: str,
    ) -> dict[str, str]:
        return await self.repository.fetch_latest_lifecycle_statuses(
            thread_id=thread_id
        )

    async def fetch_run_status(
        self,
        *,
        thread_id: str,
    ) -> WorkspaceRuntimeRunStatusRecord | None:
        return await self.repository.fetch_run_status(thread_id=thread_id)

    async def resolve_next_seq_id(
        self,
        *,
        thread_id: str,
        fallback_seq_id: int = 1,
    ) -> int:
        cursor = await self.repository.fetch_latest_cursor(thread_id=thread_id)
        candidate = max(fallback_seq_id, 1)
        if cursor is None:
            return candidate
        return max(candidate, cursor.last_seq_id + 1)

    def _build_activity_record(
        self, event: AgentEvent
    ) -> WorkspaceRuntimeActivityRecord:
        status = _extract_status(event)
        node = _extract_node(event)
        return WorkspaceRuntimeActivityRecord(
            event_id=event.id,
            thread_id=event.thread_id,
            seq_id=event.seq_id,
            run_id=event.run_id or None,
            agent_id=event.source,
            node=node,
            event_type=event.type,
            status=status,
            payload=_build_payload(event),
            created_at=_extract_timestamp(event),
        )

    async def _update_cursor(self, *, thread_id: str, seq_id: int) -> None:
        await self.repository.upsert_cursor(thread_id=thread_id, last_seq_id=seq_id)

    async def _update_activity_segments(
        self, record: WorkspaceRuntimeActivityRecord
    ) -> None:
        if record.run_id is None or not record.run_id.strip():
            return
        if record.status is None:
            return
        if record.node is None or not record.node.strip():
            return
        latest_segment = await self.repository.fetch_latest_activity_segment_by_node(
            thread_id=record.thread_id,
            agent_id=record.agent_id,
            run_id=record.run_id,
            node=record.node,
        )
        projected = project_activity_segment(
            event=record,
            latest_segment=latest_segment,
        )
        if projected is None:
            return
        if (
            latest_segment
            and projected.segment_id != latest_segment.segment_id
            and latest_segment.ended_at is None
        ):
            closed_status = (
                "done" if latest_segment.status == "running" else latest_segment.status
            )
            await self.repository.update_activity_segment(
                replace(
                    latest_segment,
                    status=closed_status,
                    updated_at=record.created_at,
                    ended_at=record.created_at,
                    last_seq_id=record.seq_id,
                )
            )
        if latest_segment and projected.segment_id == latest_segment.segment_id:
            await self.repository.update_activity_segment(projected)
            return
        await self.repository.append_activity_segment(projected)

    async def _update_run_status(self, record: WorkspaceRuntimeActivityRecord) -> None:
        if record.run_id is None or not record.run_id.strip():
            return
        latest_status = await self.repository.fetch_run_status(
            thread_id=record.thread_id
        )
        projected = project_run_status(
            event=record,
            latest_status=latest_status,
        )
        if projected is None:
            return
        await self.repository.upsert_run_status(projected)
        if projected.ended_at is not None:
            await self.repository.close_open_segments_for_run(
                thread_id=projected.thread_id,
                run_id=projected.run_id,
                status=projected.status,
                closed_at=projected.ended_at,
            )


def _extract_status(event: AgentEvent) -> str | None:
    status = event.data.get("status")
    if isinstance(status, str):
        return status
    return None


def _extract_node(event: AgentEvent) -> str | None:
    node = event.data.get("node")
    if isinstance(node, str):
        return node
    return None


def _build_payload(event: AgentEvent) -> JSONObject:
    dumped = event.model_dump(mode="json")
    return {
        "data": dumped.get("data", {}),
        "metadata": dumped.get("metadata", {}),
    }


def _extract_timestamp(event: AgentEvent) -> datetime:
    timestamp = event.timestamp
    if isinstance(timestamp, datetime):
        return timestamp
    return datetime.utcnow()


__all__ = ["WorkspaceRuntimeProjectionService"]
