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


class FundamentalValuationPreparationResultV1(BaseModel):
    """Narrow projection of the service-owned automatic preparation result.

    Agent Core validates the boundary metadata and carries the opaque service
    input forward. It does not model formulas, mappings, or policy semantics.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    status: Literal["prepared", "requires_input", "abstained", "unsupported"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    quality_status: Literal[
        "verified", "provisional", "degraded", "unsupported", "abstain", "error"
    ]
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    historical_metrics: dict[str, object]
    assumptions_evidence: tuple[dict[str, object], ...] = ()
    input: dict[str, object] | None = None
    preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def status_matches_input(
        self,
    ) -> FundamentalValuationPreparationResultV1:
        if (self.status == "prepared") != (self.input is not None):
            raise ValueError("prepared status must match the presence of input")
        return self


class FundamentalValuationEvidenceReadResultV1(BaseModel):
    """Release-bound evidence projection used after automatic preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: FundamentalIdentityV1
    valuation_timestamp: datetime
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: Literal[
        "verified", "provisional", "degraded", "unsupported", "abstain", "error"
    ]
    issue_codes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    rejected_fact_ids: tuple[str, ...] = ()
    facts: tuple[FundamentalCanonicalFactV1, ...] = ()


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
    "FundamentalCandidateRejectionV1",
    "FundamentalCanonicalFactV1",
    "FundamentalFactsReadResultV1",
    "FundamentalIdentityResolutionRequestV1",
    "FundamentalIdentityResolutionV1",
    "FundamentalIdentitySourceEvidenceV1",
    "FundamentalIdentityV1",
    "FundamentalServiceErrorV1",
    "FundamentalServiceResponseV1",
    "FundamentalValuationPreparationResultV1",
    "FundamentalValuationEvidenceReadResultV1",
    "FundamentalForwardEvidenceSourceV1",
    "FundamentalForwardEvidenceClaimV1",
    "FundamentalForwardEvidenceBudgetPolicyV1",
    "FundamentalForwardEvidenceUsageV1",
    "FundamentalForwardEvidenceReviewResultV1",
]
