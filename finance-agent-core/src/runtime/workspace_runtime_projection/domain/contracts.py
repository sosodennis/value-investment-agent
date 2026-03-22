from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class WorkspaceRuntimeActivityRecord:
    event_id: str
    thread_id: str
    seq_id: int
    run_id: str | None
    agent_id: str
    node: str | None
    event_type: str
    status: str | None
    payload: JSONObject
    created_at: datetime


@dataclass(frozen=True)
class WorkspaceRuntimeCursorRecord:
    thread_id: str
    last_seq_id: int
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceRuntimeActivitySegmentRecord:
    segment_id: str
    thread_id: str
    agent_id: str
    node: str
    run_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    last_seq_id: int


@dataclass(frozen=True)
class WorkspaceRuntimeRunStatusRecord:
    thread_id: str
    run_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    last_seq_id: int
