"""Typed port for the independently deployed Fundamental service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalActiveReleaseV1,
    FundamentalForwardEvidenceReviewResultV1,
    FundamentalIdentityResolutionRequestV1,
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
)
from src.shared.artifacts.annual_statement_contracts import (
    AnnualStatementsReadRequestV1,
    AnnualStatementsReadResponseV1,
)
from src.shared.artifacts.fiscal_statement_contracts import (
    FiscalReadRequestV2,
    FiscalReadResultV2,
)
from src.shared.artifacts.fundamental_contracts import (
    FundamentalFactsReadResultV1,
    FundamentalValuationEvidenceReadResultV1,
    FundamentalValuationPreparationResultV1,
)
from src.shared.internal_services import InternalPrincipal

FundamentalOperation = Literal[
    "ingest_sec_data",
    "resolve_identity",
    "resolve_snapshot",
    "read_facts",
    "read_annual_statements",
    "read_fiscal_statements",
    "read_active_release",
    "read_valuation_evidence",
    "prepare_valuation",
    "override_prepared_valuation",
    "review_forward_evidence",
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


class FundamentalReleaseSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    coverage_profile: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    source_selection_policy: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


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

    async def read_active_release(
        self,
        profile_id: str,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalActiveReleaseV1: ...

    async def read_facts(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalFactsReadResultV1: ...

    async def read_annual_statements(
        self,
        request: AnnualStatementsReadRequestV1,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> AnnualStatementsReadResponseV1: ...

    async def read_fiscal_statements(
        self,
        request: FiscalReadRequestV2,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FiscalReadResultV2: ...

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

    async def review_forward_evidence(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalForwardEvidenceReviewResultV1: ...

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
