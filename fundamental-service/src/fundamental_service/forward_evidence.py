"""Canonical contracts and deterministic policy for optional forward evidence.

Search and LLM adapters live at the caller boundary. This module owns the
meaning of a forward claim, its evidence requirements, and the disposition
that the Fundamental service exposes to reviewers.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from .contracts import InitialModelId, StrictModel
from .serialization import sha256_digest

FORWARD_EVIDENCE_POLICY_VERSION = "forward-evidence-policy-v1"
FORWARD_EVIDENCE_LABEL = "forward-looking external evidence"
FORWARD_EVIDENCE_MAX_AGE_DAYS = 365


class ForwardEvidenceMetric(str, Enum):
    REVENUE_GROWTH = "revenue_growth"
    OPERATING_MARGIN = "operating_margin"
    REINVESTMENT_RATE = "reinvestment_rate"
    DEBT_TERM = "debt_term"


class ForwardEvidencePeriodType(str, Enum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class ForwardEvidenceExtractionMethod(str, Enum):
    STRUCTURED_PROVIDER = "structured_provider"
    LLM_FROM_SOURCE_PASSAGE = "llm_from_source_passage"


class ForwardEvidenceLicenseStatus(str, Enum):
    APPROVED = "approved"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class ForwardEvidenceClaimStatus(str, Enum):
    ACCEPTED = "accepted"
    EXCLUDED = "excluded"


class ForwardEvidenceSourceV1(StrictModel):
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
    license_status: ForwardEvidenceLicenseStatus
    license_reference: str | None = Field(default=None, max_length=2048)

    @field_validator("source_url")
    @classmethod
    def http_url_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an http or https URL")
        return value

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> ForwardEvidenceSourceV1:
        for name, value in (
            ("published_at", self.published_at),
            ("retrieved_at", self.retrieved_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if self.retrieved_at < self.published_at:
            raise ValueError("retrieved_at cannot precede published_at")
        if self.license_status is ForwardEvidenceLicenseStatus.APPROVED and not (
            self.license_reference and self.license_reference.strip()
        ):
            raise ValueError("approved sources require a license reference")
        return self


class ForwardEvidenceClaimV1(StrictModel):
    claim_id: str = Field(min_length=1, max_length=256)
    issuer_id: str = Field(min_length=1, max_length=256)
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    model_id: InitialModelId
    metric: ForwardEvidenceMetric
    assumption_path: str | None = Field(default=None, max_length=256)
    value: Decimal
    unit: Literal["ratio", "currency", "days", "text"]
    fiscal_period: str = Field(min_length=2, max_length=32)
    period_type: ForwardEvidencePeriodType
    period_end: date
    extraction_method: ForwardEvidenceExtractionMethod
    source: ForwardEvidenceSourceV1
    status: ForwardEvidenceClaimStatus
    issue_codes: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def status_has_reason(self) -> ForwardEvidenceClaimV1:
        if self.status is ForwardEvidenceClaimStatus.EXCLUDED and not (
            self.issue_codes or self.exclusion_reasons
        ):
            raise ValueError("excluded claims require a typed exclusion reason")
        if self.status is ForwardEvidenceClaimStatus.ACCEPTED and (
            self.issue_codes or self.exclusion_reasons
        ):
            raise ValueError("accepted claims cannot carry exclusion reasons")
        return self


class ForwardEvidenceBudgetPolicyV1(StrictModel):
    policy_version: str = FORWARD_EVIDENCE_POLICY_VERSION
    max_search_queries: int = Field(default=2, ge=1, le=5)
    max_results_per_query: int = Field(default=5, ge=1, le=20)
    max_source_bytes: int = Field(default=120_000, ge=1_000, le=1_000_000)
    max_llm_claims: int = Field(default=8, ge=1, le=32)
    max_duration_ms: int = Field(default=15_000, ge=500, le=120_000)


class ForwardEvidenceUsageV1(StrictModel):
    search_queries: int = Field(default=0, ge=0)
    search_results: int = Field(default=0, ge=0)
    source_fetches: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    llm_input_bytes: int = Field(default=0, ge=0)
    llm_output_tokens: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)


class ForwardEvidenceReviewRequestV1(StrictModel):
    """Service review request; ``opt_in`` makes the boundary explicit."""

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    opt_in: Literal[True]
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    issuer_id: str = Field(min_length=1, max_length=256)
    model_id: InitialModelId
    assumption_path: str = Field(min_length=1, max_length=256)
    valuation_timestamp: datetime
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: tuple[ForwardEvidenceClaimV1, ...] = Field(max_length=32)
    budget: ForwardEvidenceBudgetPolicyV1 = Field(
        default_factory=ForwardEvidenceBudgetPolicyV1
    )
    usage: ForwardEvidenceUsageV1 = Field(default_factory=ForwardEvidenceUsageV1)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def timestamp_has_timezone(self) -> ForwardEvidenceReviewRequestV1:
        if (
            self.valuation_timestamp.tzinfo is None
            or self.valuation_timestamp.utcoffset() is None
        ):
            raise ValueError("valuation_timestamp must include a timezone")
        if self.valuation_timestamp.tzinfo is not UTC:
            self = self.model_copy(
                update={"valuation_timestamp": self.valuation_timestamp.astimezone(UTC)}
            )
        return self


class ForwardEvidenceReviewResponseV1(StrictModel):
    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    status: Literal["prepared", "unsupported", "unavailable"]
    label: Literal[FORWARD_EVIDENCE_LABEL] = FORWARD_EVIDENCE_LABEL
    policy_version: str = FORWARD_EVIDENCE_POLICY_VERSION
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: tuple[ForwardEvidenceClaimV1, ...] = ()
    accepted_claim_ids: tuple[str, ...] = ()
    excluded_claim_ids: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()
    budget: ForwardEvidenceBudgetPolicyV1
    usage: ForwardEvidenceUsageV1
    reference_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


_SUPPORTED_PATHS = {
    "assumptions.forecast.revenue_growth[0]",
    "assumptions.forecast.revenue_growth[1]",
    "assumptions.forecast.revenue_growth[2]",
    "assumptions.forecast.revenue_growth[3]",
    "assumptions.forecast.revenue_growth[4]",
    "assumptions.forecast.operating_margin[0]",
    "assumptions.forecast.operating_margin[1]",
    "assumptions.forecast.operating_margin[2]",
    "assumptions.forecast.operating_margin[3]",
    "assumptions.forecast.operating_margin[4]",
    "assumptions.forecast.reinvestment_rate[0]",
    "assumptions.forecast.reinvestment_rate[1]",
    "assumptions.forecast.reinvestment_rate[2]",
    "assumptions.forecast.reinvestment_rate[3]",
    "assumptions.forecast.reinvestment_rate[4]",
}


def _content_hash(source: ForwardEvidenceSourceV1) -> str:
    return hashlib.sha256(source.retained_passage.encode("utf-8")).hexdigest()


def _append_issue(claim: ForwardEvidenceClaimV1, code: str) -> ForwardEvidenceClaimV1:
    return claim.model_copy(
        update={
            "status": ForwardEvidenceClaimStatus.EXCLUDED,
            "issue_codes": tuple(dict.fromkeys((*claim.issue_codes, code))),
            "exclusion_reasons": tuple(dict.fromkeys((*claim.exclusion_reasons, code))),
        }
    )


def review_forward_evidence(
    request: ForwardEvidenceReviewRequestV1,
) -> ForwardEvidenceReviewResponseV1:
    """Apply the service-owned quality gate without provider or network calls."""

    claims: list[ForwardEvidenceClaimV1] = []
    for claim in request.claims:
        current = claim
        if claim.ticker != request.ticker or claim.issuer_id != request.issuer_id:
            current = _append_issue(current, "ISSUER_MISMATCH")
        if claim.model_id != request.model_id:
            current = _append_issue(current, "MODEL_MISMATCH")
        if request.assumption_path not in _SUPPORTED_PATHS:
            current = _append_issue(current, "ASSUMPTION_PATH_UNSUPPORTED")
        elif claim.assumption_path != request.assumption_path:
            current = _append_issue(current, "ASSUMPTION_PATH_MISMATCH")
        if (
            claim.extraction_method
            is ForwardEvidenceExtractionMethod.LLM_FROM_SOURCE_PASSAGE
        ):
            if not claim.source.retained_passage.strip():
                current = _append_issue(current, "SOURCE_CITATION_MISSING")
        if claim.source.content_hash != _content_hash(claim.source):
            current = _append_issue(current, "SOURCE_CONTENT_HASH_MISMATCH")
        if claim.source.license_status is not ForwardEvidenceLicenseStatus.APPROVED:
            current = _append_issue(current, "SOURCE_LICENSE_NOT_APPROVED")
        if claim.source.published_at > request.valuation_timestamp:
            current = _append_issue(current, "SOURCE_PUBLISHED_AFTER_VALUATION")
        elif request.valuation_timestamp - claim.source.published_at > timedelta(
            days=FORWARD_EVIDENCE_MAX_AGE_DAYS
        ):
            current = _append_issue(current, "SOURCE_STALE")
        if claim.period_end <= request.valuation_timestamp.date():
            current = _append_issue(current, "FORWARD_PERIOD_MISMATCH")
        if claim.metric is ForwardEvidenceMetric.DEBT_TERM:
            current = _append_issue(current, "REFERENCE_ONLY_METRIC")
        claims.append(current)

    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, claim in enumerate(claims):
        if claim.status is ForwardEvidenceClaimStatus.ACCEPTED:
            grouped[(claim.metric.value, claim.fiscal_period, claim.unit)].append(index)
    for indexes in grouped.values():
        values = {claims[index].value for index in indexes}
        if len(values) > 1:
            for index in indexes:
                claims[index] = _append_issue(claims[index], "CONFLICTING_SOURCES")

    accepted = tuple(
        claim.claim_id
        for claim in claims
        if claim.status is ForwardEvidenceClaimStatus.ACCEPTED
    )
    excluded = tuple(
        claim.claim_id
        for claim in claims
        if claim.status is ForwardEvidenceClaimStatus.EXCLUDED
    )
    issue_codes = tuple(
        dict.fromkeys(code for claim in claims for code in claim.issue_codes)
    )
    status: Literal["prepared", "unsupported", "unavailable"] = (
        "prepared" if accepted else "unsupported"
    )
    payload = {
        "status": status,
        "label": FORWARD_EVIDENCE_LABEL,
        "policy_version": FORWARD_EVIDENCE_POLICY_VERSION,
        "automatic_preparation_digest": request.automatic_preparation_digest,
        "claims": tuple(claims),
        "accepted_claim_ids": accepted,
        "excluded_claim_ids": excluded,
        "issue_codes": issue_codes,
        "budget": request.budget,
        "usage": request.usage,
    }
    return ForwardEvidenceReviewResponseV1(
        **payload,
        reference_digest=sha256_digest(payload),
    )


__all__ = [
    "FORWARD_EVIDENCE_LABEL",
    "FORWARD_EVIDENCE_MAX_AGE_DAYS",
    "FORWARD_EVIDENCE_POLICY_VERSION",
    "ForwardEvidenceBudgetPolicyV1",
    "ForwardEvidenceClaimStatus",
    "ForwardEvidenceClaimV1",
    "ForwardEvidenceExtractionMethod",
    "ForwardEvidenceLicenseStatus",
    "ForwardEvidenceMetric",
    "ForwardEvidencePeriodType",
    "ForwardEvidenceReviewRequestV1",
    "ForwardEvidenceReviewResponseV1",
    "ForwardEvidenceSourceV1",
    "ForwardEvidenceUsageV1",
    "review_forward_evidence",
]
