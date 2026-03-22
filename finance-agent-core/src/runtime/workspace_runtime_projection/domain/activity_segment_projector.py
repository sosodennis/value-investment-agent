from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
)

_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"running", "done", "error", "attention", "degraded"}
)
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"done", "error", "attention", "degraded"}
)


def project_activity_segment(
    *,
    event: WorkspaceRuntimeActivityRecord,
    latest_segment: WorkspaceRuntimeActivitySegmentRecord | None,
) -> WorkspaceRuntimeActivitySegmentRecord | None:
    status = event.status
    if status is None or status not in _ALLOWED_STATUSES:
        return None
    run_id = event.run_id
    if run_id is None or not run_id.strip():
        return None
    node = event.node
    if node is None or not node.strip():
        return None
    event_time = event.created_at
    is_terminal = status in _TERMINAL_STATUSES
    if (
        latest_segment
        and latest_segment.thread_id == event.thread_id
        and latest_segment.agent_id == event.agent_id
        and latest_segment.run_id == run_id
        and latest_segment.node == node
    ):
        if latest_segment.ended_at is None:
            return replace(
                latest_segment,
                status=status,
                updated_at=event_time,
                ended_at=event_time if is_terminal else None,
                last_seq_id=event.seq_id,
            )
        if is_terminal:
            if latest_segment.status == status:
                return None
            return replace(
                latest_segment,
                status=status,
                updated_at=event_time,
                ended_at=event_time,
                last_seq_id=event.seq_id,
            )

    return WorkspaceRuntimeActivitySegmentRecord(
        segment_id=str(uuid4()),
        thread_id=event.thread_id,
        agent_id=event.agent_id,
        node=node,
        run_id=run_id,
        status=status,
        started_at=event_time,
        updated_at=event_time,
        ended_at=event_time if is_terminal else None,
        last_seq_id=event.seq_id,
    )


__all__ = ["project_activity_segment"]
