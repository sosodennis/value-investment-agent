from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActivityStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "skipped",
]
ActivityKind = Literal["phase", "node", "tool", "subgraph"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
]


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    parent_activity_id: str | None = Field(default=None, min_length=1)
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    scope_path: tuple[str, ...] = Field(min_length=1)
    kind: ActivityKind
    status: ActivityStatus
    label: str = Field(min_length=1, max_length=160)
    progress: float | None = Field(default=None, ge=0, le=100)
    attempt: int = Field(ge=1)


class ActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    seq_id: int = Field(ge=1)
    event_version: Literal["v1"] = "v1"
    event_name: Literal["workflow.activity"] = "workflow.activity"
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    occurred_at: datetime
    payload: Activity


class RunStatusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None


class ActivitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    run_status: RunStatus
    cursor: int = Field(ge=0)
    active_activities: tuple[Activity, ...] = ()
    recent_activities: tuple[Activity, ...] = ()


class ReplayPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: tuple[ActivityEvent, ...]
    cursor: int
    has_more: bool
