from __future__ import annotations

from dataclasses import replace

from .contracts import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeRunStatusRecord,
)

_ALLOWED_RUN_STATUSES: frozenset[str] = frozenset(
    {"running", "attention", "done", "error", "degraded"}
)
_TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"done", "error", "degraded"})


def project_run_status(
    *,
    event: WorkspaceRuntimeActivityRecord,
    latest_status: WorkspaceRuntimeRunStatusRecord | None,
) -> WorkspaceRuntimeRunStatusRecord | None:
    run_id = event.run_id
    if run_id is None or not run_id.strip():
        return None
    if latest_status and latest_status.run_id != run_id:
        return None

    if event.event_type == "lifecycle.status":
        status = event.status
        if status is None or status not in _ALLOWED_RUN_STATUSES:
            return None
    elif event.event_type == "interrupt.request":
        status = "attention"
    elif event.event_type == "error":
        status = "error"
    else:
        return None

    event_time = event.created_at
    is_terminal = status in _TERMINAL_RUN_STATUSES

    if latest_status:
        return replace(
            latest_status,
            status=status,
            updated_at=event_time,
            ended_at=event_time if is_terminal else None,
            last_seq_id=event.seq_id,
        )

    return WorkspaceRuntimeRunStatusRecord(
        thread_id=event.thread_id,
        run_id=run_id,
        status=status,
        started_at=event_time,
        updated_at=event_time,
        ended_at=event_time if is_terminal else None,
        last_seq_id=event.seq_id,
    )


__all__ = ["project_run_status"]
