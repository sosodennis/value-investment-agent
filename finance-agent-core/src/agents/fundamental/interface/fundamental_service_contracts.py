"""Agent-owned wire projections for the Fundamental service boundary."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.internal_services import INTERNAL_CONTRACT_VERSION


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


class FundamentalIdentityV1(BaseModel):
    """Identity pinned by a service-owned snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_id: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    domicile: str = Field(min_length=2, max_length=2)
    reporting_basis: Literal["us-gaap", "ifrs"]
    security_id: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


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
    "FundamentalCanonicalFactV1",
    "FundamentalFactsReadResultV1",
    "FundamentalServiceErrorV1",
    "FundamentalServiceResponseV1",
]
