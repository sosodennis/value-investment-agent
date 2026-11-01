"""Transport-neutral wire primitives for internal capability service calls.

Service-specific request and response payloads deliberately do not live here.
This module only owns values that every independently deployed service must
understand in the same way.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

INTERNAL_CONTRACT_VERSION = "internal.v1"


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InternalPrincipal(_WireModel):
    """Authenticated application identity, without browser or provider secrets."""

    subject_id: str = Field(min_length=1, max_length=256)
    organization_id: str | None = Field(default=None, min_length=1, max_length=128)
    membership_id: str | None = Field(default=None, min_length=1, max_length=128)


class InternalRequestContext(_WireModel):
    """Request metadata accepted by an internal capability service."""

    principal: InternalPrincipal
    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    deadline_at: datetime
    audience: str | None = Field(default=None, min_length=1, max_length=128)
    issuer: str | None = Field(default=None, min_length=1, max_length=128)
    issued_at: datetime | None = None
    signature: str | None = Field(default=None, min_length=64, max_length=128)

    @field_validator("deadline_at", mode="before")
    @classmethod
    def parse_utc_deadline(cls, value: object) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(
                    value[:-1] + "+00:00" if value.endswith("Z") else value
                )
            except ValueError as exc:
                raise ValueError("deadline_at must be an ISO 8601 timestamp") from exc
        if not isinstance(value, datetime):
            raise ValueError("deadline_at must be an ISO 8601 timestamp")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("issued_at", mode="before")
    @classmethod
    def parse_utc_issued_at(cls, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(
                    value[:-1] + "+00:00" if value.endswith("Z") else value
                )
            except ValueError as exc:
                raise ValueError("issued_at must be an ISO 8601 timestamp") from exc
        if not isinstance(value, datetime):
            raise ValueError("issued_at must be an ISO 8601 timestamp")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class InternalError(_WireModel):
    """Redacted, stable failure metadata shared by internal service responses."""

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)


class InternalErrorResponse(_WireModel):
    """Versioned error response envelope; operation details stay service-owned."""

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    error: InternalError


class ReadinessStatus(str, Enum):
    READY = "ready"
    NOT_READY = "not_ready"


class InternalReadiness(_WireModel):
    """Response body for the shared ``/readyz`` convention."""

    status: ReadinessStatus
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
