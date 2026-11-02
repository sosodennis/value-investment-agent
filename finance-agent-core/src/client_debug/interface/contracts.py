from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from src.client_debug.config import MAX_CLIENT_DEBUG_REQUEST_BYTES
from src.client_debug.domain import require_safe_route, sanitize_details

_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,95}$")
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<parent_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


class ClientDebugViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=0, le=10_000)
    height: int = Field(ge=0, le=10_000)
    dpr: float = Field(gt=0, le=10)


class ClientDebugScroll(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("client debug scroll values must be finite")
        return value


class ClientDebugContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1, max_length=512)
    viewport: ClientDebugViewport
    scroll: ClientDebugScroll | None = None
    visibility_state: Literal["visible", "hidden", "prerender"] = "visible"
    reduced_motion: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    traceparent: str | None = Field(default=None, min_length=1, max_length=512)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("route")
    @classmethod
    def pathname_only(cls, value: str) -> str:
        return require_safe_route(value)

    @field_validator("traceparent")
    @classmethod
    def valid_traceparent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _TRACEPARENT.fullmatch(value)
        if match is None:
            raise ValueError("client debug traceparent has an invalid format")
        if match.group("version") == "ff":
            raise ValueError("client debug traceparent uses a reserved version")
        if set(match.group("trace_id")) == {"0"}:
            raise ValueError("client debug traceparent has an invalid trace ID")
        if set(match.group("parent_id")) == {"0"}:
            raise ValueError("client debug traceparent has an invalid parent ID")
        return value


class ClientDebugEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    sequence: int = Field(ge=1, le=1_000_000_000)
    occurred_at: datetime
    elapsed_ms: float = Field(ge=0)
    name: str = Field(pattern=_EVENT_NAME.pattern)
    severity: Literal["debug", "info", "warn", "error"] = "debug"
    component: str | None = Field(default=None, min_length=1, max_length=160)
    context: ClientDebugContext
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("client debug occurred_at must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("elapsed_ms")
    @classmethod
    def finite_elapsed(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("client debug elapsed_ms must be finite")
        return value

    @model_validator(mode="after")
    def validate_details(self) -> ClientDebugEvent:
        self.details = sanitize_details(self.details)
        return self


class ClientDebugBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["client_debug.v1"]
    capture_id: UUID
    events: list[ClientDebugEvent] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_payload_size(self) -> ClientDebugBatchRequest:
        encoded = self.model_dump_json().encode("utf-8")
        if len(encoded) > MAX_CLIENT_DEBUG_REQUEST_BYTES:
            raise ValueError("client debug request exceeds the 256 KiB limit")
        return self


class ClientDebugAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["client_debug.v1"] = "client_debug.v1"
    capture_id: UUID
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    dropped: int = Field(ge=0)
    dropped_rate_limited: int = Field(ge=0)
    dropped_capacity: int = Field(ge=0)
    request_id: str | None = None


class ClientDebugEventResponse(ClientDebugEvent):
    received_at: datetime


class ClientDebugCaptureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["client_debug.v1"] = "client_debug.v1"
    capture_id: UUID
    events: list[ClientDebugEventResponse]
    next_seq: int = Field(ge=0)
    expires_at: datetime
