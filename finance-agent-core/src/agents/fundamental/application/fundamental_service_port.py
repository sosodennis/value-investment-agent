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
    FundamentalValuationEvidenceReadResultV1,
    FundamentalValuationPreparationResultV1,
)
from src.shared.internal_services import InternalPrincipal

FundamentalOperation = Literal[
    "ingest_sec_data",
    "resolve_identity",
    "resolve_snapshot",
    "read_facts",
    "read_valuation_evidence",
    "prepare_valuation",
    "validate",
    "validate_with_policy",
    "calculate",
    "uncertainty",
    "replay",
]

# The caller deadline must cover the Fundamental service's bounded SEC parser
# budget; a shorter workflow deadline aborts valid ingestion before the service
# can publish its immutable snapshot.
FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS = 120.0


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

    async def prepare_valuation(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalValuationPreparationResultV1: ...

    async def read_valuation_evidence(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalValuationEvidenceReadResultV1: ...

    async def resolve_identity(
        self,
        request: FundamentalIdentityResolutionRequestV1,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalIdentityResolutionV1: ...


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
    "FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS",
    "FundamentalOperation",
    "FundamentalServiceClient",
    "FundamentalServiceFailure",
    "FundamentalIdentityResolver",
]
