"""Agent-owned wire projections for the Fundamental service boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.shared.internal_services import INTERNAL_CONTRACT_VERSION


class FundamentalIdentityResolutionRequestV1(BaseModel):
    """Agent-owned request projection for selected-ticker identity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FundamentalIdentityV1(BaseModel):
    """Identity pinned by a service-owned snapshot or resolver result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    issuer_id: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    domicile: str = Field(min_length=2, max_length=2)
    reporting_basis: Literal["us-gaap", "ifrs"]
    security_id: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


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
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    schema_version: Literal["fundamental.v1"]
    result: dict[str, object]


class FundamentalServiceErrorV1(BaseModel):
    """Stable error projection used by the typed client implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    error: dict[str, object]


class FundamentalDimensionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    member: str = Field(min_length=1)


class FundamentalXbrlContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_qname: str = Field(min_length=1)
    period_type: Literal["instant", "duration"]
    start_date: date | None = None
    end_date: date | None = None
    instant: date | None = None
    unit_qname: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    dimensions: tuple[FundamentalDimensionV1, ...] = ()
    entity_scope: str = Field(min_length=1)
    consolidation_scope: str = Field(min_length=1)
    context_id: str = Field(min_length=1)


class FundamentalSourceProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_role: Literal[
        "filing",
        "company_facts",
        "taxonomy",
        "acquisition",
        "macro",
        "market",
        "reference",
    ]
    captured_at: datetime
    available_at: datetime
    filed_at: datetime | None = None
    accession_number: str | None = None
    parser_version: str = Field(min_length=1)
    taxonomy_version: str | None = None
    terms_reference: str | None = None


class FundamentalMissingValueV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["missing", "not_applicable", "unsupported", "unresolved"]
    reason: str = Field(min_length=1)


class FundamentalCandidateRejectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class FundamentalCanonicalFactV1(BaseModel):
    """Typed fact projection; no browser or Agent-side SEC fallback is implied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    fact_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    security_id: str | None = None
    concept: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    value: Decimal | str | bool | FundamentalMissingValueV1
    unit: str = Field(min_length=1)
    scale: int
    currency: str | None = None
    period_start: date | None = None
    period_end: date
    instant: date | None = None
    context: FundamentalXbrlContextV1
    security_scope: str | None = None
    as_of: datetime
    available_at: datetime
    filed_at: datetime | None = None
    captured_at: datetime
    accession_number: str | None = None
    filing_version: str | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    decimals: int | None = None
    taxonomy_version: str = Field(min_length=1)
    source: FundamentalSourceProvenanceV1
    quality: Literal[
        "verified", "provisional", "degraded", "unsupported", "abstain", "error"
    ]
    issue_codes: tuple[str, ...] = ()
    mapping_decision_id: str | None = None
    mapping_confidence: Literal["high", "medium", "low", "unresolved"] | None = None
    rejected_candidates: tuple[str, ...] = ()
    rejected_candidate_reasons: tuple[FundamentalCandidateRejectionV1, ...] = ()
    point_in_time_policy: str | None = None
    selection_reason: str | None = None


class FundamentalFactsReadResultV1(BaseModel):
    """Immutable fact selection returned for one valuation snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: FundamentalIdentityV1
    valuation_timestamp: datetime
    quality_status: Literal[
        "verified", "provisional", "degraded", "unsupported", "abstain", "error"
    ]
    issue_codes: tuple[str, ...] = ()
    facts: tuple[FundamentalCanonicalFactV1, ...] = Field(min_length=1)


__all__ = [
    "FundamentalCandidateRejectionV1",
    "FundamentalCanonicalFactV1",
    "FundamentalFactsReadResultV1",
    "FundamentalIdentityResolutionRequestV1",
    "FundamentalIdentityResolutionV1",
    "FundamentalIdentitySourceEvidenceV1",
    "FundamentalIdentityV1",
    "FundamentalServiceErrorV1",
    "FundamentalServiceResponseV1",
]
