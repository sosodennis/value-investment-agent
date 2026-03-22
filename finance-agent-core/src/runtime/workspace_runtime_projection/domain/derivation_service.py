from __future__ import annotations

from collections.abc import Iterable

from .contracts import WorkspaceRuntimeActivityRecord

_ACTIVE_STATUSES: tuple[str, ...] = ("running", "attention", "degraded")


def derive_active_agent_id(
    records: Iterable[WorkspaceRuntimeActivityRecord],
) -> str | None:
    ordered = list(records)
    for record in reversed(ordered):
        if record.event_type != "agent.lifecycle":
            continue
        if record.status in _ACTIVE_STATUSES:
            return record.agent_id
    return None


def derive_recent_activity(
    records: Iterable[WorkspaceRuntimeActivityRecord],
    *,
    limit: int = 20,
) -> tuple[WorkspaceRuntimeActivityRecord, ...]:
    if limit <= 0:
        return ()
    ordered = sorted(records, key=lambda record: record.created_at, reverse=True)
    return tuple(ordered[:limit])
