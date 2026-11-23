"""Agent-owned wire projections for the Fundamental service boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.shared.artifacts.fundamental_contracts import FundamentalIdentityV1


class FundamentalIdentityResolutionRequestV1(BaseModel):
    """Agent-owned request projection for selected-ticker identity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FundamentalIdentitySourceEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_id: Literal["sec-company-tickers", "sec-submissions", "sec-companyfacts"]
    source_uri: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    available_at: datetime
    media_type: Literal["application/json"]
    byte_count: int = Field(ge=0)

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> FundamentalIdentitySourceEvidenceV1:
        for name, value in (
            ("captured_at", self.captured_at),
            ("available_at", self.available_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        return self


class FundamentalIdentityResolutionV1(BaseModel):
    """Typed Agent projection of the service's verified identity result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    identity: FundamentalIdentityV1
    mapping_version: Literal["sec-issuer-identity-v1"]
    source_evidence: tuple[FundamentalIdentitySourceEvidenceV1, ...] = Field(
        min_length=3, max_length=3
    )
    resolution_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def response_is_bound_to_evidence(self) -> FundamentalIdentityResolutionV1:
        expected_source_ids = {
            "sec-company-tickers",
            "sec-submissions",
            "sec-companyfacts",
        }
        if {source.source_id for source in self.source_evidence} != expected_source_ids:
            raise ValueError("identity response requires all SEC source evidence")
        if (
            self.identity.domicile != "US"
            or self.identity.reporting_basis != "us-gaap"
            or self.identity.currency != "USD"
        ):
            raise ValueError("SEC identity response must use the US GAAP/USD profile")
        if (
            self.identity.security_id != self.ticker
            or self.identity.share_class != self.ticker
        ):
            raise ValueError("identity response must retain the selected ticker key")
        payload = self.model_dump(mode="json", exclude={"resolution_digest"})
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != self.resolution_digest:
            raise ValueError("resolution_digest does not bind identity evidence")
        return self


class FundamentalServiceResponseV1(BaseModel):
    """Shared response metadata plus an opaque, service-owned result projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"]
    schema_version: Literal["fundamental.v1"]
    result: dict[str, object]


class FundamentalServiceErrorV1(BaseModel):
    """Stable error projection used by the typed client implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"]
    error: dict[str, object]


class FundamentalForwardEvidenceSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_id: str = Field(min_length=1, max_length=256)
    source_url: str = Field(min_length=1, max_length=2048)
    publisher: str = Field(min_length=1, max_length=256)
    source_type: Literal[
        "issuer_guidance", "analyst_estimate", "debt_terms", "search_discovery"
    ]
    retained_passage: str = Field(min_length=20, max_length=8192)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    retrieved_at: datetime
    license_status: Literal["approved", "unknown", "rejected"]
    license_reference: str | None = Field(default=None, max_length=2048)


class FundamentalForwardEvidenceClaimV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim_id: str = Field(min_length=1, max_length=256)
    issuer_id: str = Field(min_length=1, max_length=256)
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    metric: Literal[
        "revenue_growth", "operating_margin", "reinvestment_rate", "debt_term"
    ]
    assumption_path: str | None = Field(default=None, max_length=256)
    value: Decimal
    unit: Literal["ratio", "currency", "days", "text"]
    fiscal_period: str = Field(min_length=2, max_length=32)
    period_type: Literal["annual", "quarterly"]
    period_end: date
    extraction_method: Literal["structured_provider", "llm_from_source_passage"]
    source: FundamentalForwardEvidenceSourceV1
    status: Literal["accepted", "excluded"]
    issue_codes: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()


class FundamentalForwardEvidenceBudgetPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: str = "forward-evidence-policy-v1"
    max_search_queries: int = Field(default=2, ge=1, le=5)
    max_results_per_query: int = Field(default=5, ge=1, le=20)
    max_source_bytes: int = Field(default=120_000, ge=1_000, le=1_000_000)
    max_llm_claims: int = Field(default=8, ge=1, le=32)
    max_duration_ms: int = Field(default=15_000, ge=500, le=120_000)


class FundamentalForwardEvidenceUsageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    search_queries: int = Field(default=0, ge=0)
    search_results: int = Field(default=0, ge=0)
    source_fetches: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    llm_input_bytes: int = Field(default=0, ge=0)
    llm_output_tokens: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)


class FundamentalForwardEvidenceReviewResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal["fundamental.v1"]
    status: Literal["prepared", "unsupported", "unavailable"]
    label: Literal["forward-looking external evidence"]
    policy_version: str
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: tuple[FundamentalForwardEvidenceClaimV1, ...] = ()
    accepted_claim_ids: tuple[str, ...] = ()
    excluded_claim_ids: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()
    budget: FundamentalForwardEvidenceBudgetPolicyV1
    usage: FundamentalForwardEvidenceUsageV1
    reference_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "FundamentalIdentityResolutionRequestV1",
    "FundamentalIdentityResolutionV1",
    "FundamentalIdentitySourceEvidenceV1",
    "FundamentalServiceErrorV1",
    "FundamentalServiceResponseV1",
    "FundamentalForwardEvidenceSourceV1",
    "FundamentalForwardEvidenceClaimV1",
    "FundamentalForwardEvidenceBudgetPolicyV1",
    "FundamentalForwardEvidenceUsageV1",
    "FundamentalForwardEvidenceReviewResultV1",
]
