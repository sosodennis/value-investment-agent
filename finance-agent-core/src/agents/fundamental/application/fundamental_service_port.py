"""Typed port for the independently deployed Fundamental service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol

from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalFactsReadResultV1,
    FundamentalIdentityResolutionRequestV1,
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
)
from src.shared.internal_services import InternalPrincipal

FundamentalOperation = Literal[
    "ingest_sec_data",
    "resolve_identity",
    "resolve_snapshot",
    "read_facts",
    "validate",
    "calculate",
    "uncertainty",
    "replay",
]


class FundamentalServiceFailure(RuntimeError):
    """A typed unavailable/degraded outcome from the service boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_ms = retry_after_ms


class FundamentalServiceClient(Protocol):
    """Caller-owned transport port; no Fundamental implementation dependency."""

    async def execute(
        self,
        operation: FundamentalOperation,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalServiceResponseV1: ...

    async def read_facts(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalFactsReadResultV1: ...


class FundamentalIdentityResolver(Protocol):
    """Typed caller port for SEC-backed issuer identity resolution."""

    async def resolve_identity(
        self,
        request: FundamentalIdentityResolutionRequestV1,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalIdentityResolutionV1: ...


__all__ = [
    "FundamentalOperation",
    "FundamentalServiceClient",
    "FundamentalServiceFailure",
    "FundamentalIdentityResolver",
]
