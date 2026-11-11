"""Strict public and internal contracts for the first Fundamental service slice."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .historical_dqc import V1_PROFILE, V3_PROFILE
from .numerical_policy import using_valuation_context
from .serialization import is_digest, sha256_digest
from .accounting_roles import AccountingRoleEvidenceV1, accounting_reported_decimals

_MANIFEST_STRINGS = TypeAdapter(tuple[str, ...])

# The public contract names every model family that may appear in a governed
# inventory.  Only released families are accepted by the calculator; the
# remaining values exist so callers receive an explicit unsupported decision
# instead of a schema-level or hidden fallback.
ModelId = Literal[
    "fcff_dcf",
    "transition_fcff_dcf",
    "bank_excess_return",
    "insurance_statutory_excess_return",
    "reit_nav",
    "regulated_utility",
    "normalized_cyclical",
    "biotech_rnpv",
    "sum_of_parts",
    "ifrs_fcff_dcf",
]
InitialModelId = Literal["fcff_dcf", "transition_fcff_dcf"]
BankFactField = Literal[
    "current_book_value",
    "tangible_book_value",
    "reported_rwa",
    "cet1_capital",
    "diluted_shares",
    "regulatory_entity",
    "issuer_entity_relationship",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class QualityStatus(str, Enum):
    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    ABSTAIN = "abstain"
    ERROR = "error"


class CalculationStatus(str, Enum):
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class SourceRole(str, Enum):
    FILING = "filing"
    FACTS = "company_facts"
    TAXONOMY = "taxonomy"
    ACQUISITION = "acquisition"
    MACRO = "macro"
    MARKET = "market"
    REFERENCE = "reference"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class PeriodType(str, Enum):
    INSTANT = "instant"
    DURATION = "duration"


class SourceProvenanceV1(StrictModel):
    source_url: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_role: SourceRole
    captured_at: datetime
    available_at: datetime
    filed_at: datetime | None = None
    accession_number: str | None = None
    parser_version: str = Field(min_length=1)
    taxonomy_version: str | None = None
    terms_reference: str | None = None

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> SourceProvenanceV1:
        for name, value in (
            ("captured_at", self.captured_at),
            ("available_at", self.available_at),
            ("filed_at", self.filed_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        return self


class IssueV1(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    severity: Severity
    message: str = Field(min_length=1)
    field: str | None = None


class TraceV1(StrictModel):
    source_refs: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    source_uris: tuple[str, ...] = ()
    source_versions: tuple[str, ...] = ()
    terms_references: tuple[str, ...] = ()
    as_of: datetime | None = None
    available_at: datetime | None = None
    captured_at: datetime | None = None
    expression: str | None = None
    inputs: tuple[str, ...] = ()
    description: str | None = None

    @model_validator(mode="after")
    def require_trace(self) -> TraceV1:
        if not self.source_refs and not self.expression and not self.description:
            raise ValueError("a trace requires source_refs, expression, or description")
        for name, value in (
            ("as_of", self.as_of),
            ("available_at", self.available_at),
            ("captured_at", self.captured_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        if (
            self.as_of is not None
            and self.available_at is not None
            and self.as_of > self.available_at
        ):
            raise ValueError("trace cannot be available before its as_of time")
        if (
            self.available_at is not None
            and self.captured_at is not None
            and self.available_at > self.captured_at
        ):
            raise ValueError("trace cannot be captured before availability")
        return self


class MarketPolicyEvidenceV1(StrictModel):
    """One dated, replayable source or policy reference for a market input."""

    role: str = Field(min_length=1)
    method: Literal["observed_source", "approved_policy"]
    value: Decimal | None = None
    source_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_version: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    as_of: datetime
    available_at: datetime
    captured_at: datetime
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamps_and_order(self) -> MarketPolicyEvidenceV1:
        for name, value in (
            ("as_of", self.as_of),
            ("available_at", self.available_at),
            ("captured_at", self.captured_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if self.as_of > self.available_at:
            raise ValueError(
                "market evidence cannot be available before its as_of time"
            )
        if self.available_at > self.captured_at:
            raise ValueError("market evidence cannot be captured before availability")
        return self


class MarketPolicyInputsV1(StrictModel):
    """Versioned service-owned WACC inputs with per-role evidence."""

    policy_version: str = Field(min_length=1)
    capital_weight_basis: Literal["market_observed", "approved_policy"] = (
        "approved_policy"
    )
    risk_free_rate: Decimal
    beta: Decimal
    equity_risk_premium: Decimal
    pre_tax_cost_of_debt: Decimal
    debt_weight: Decimal
    equity_weight: Decimal
    terminal_growth: Decimal
    evidence: tuple[MarketPolicyEvidenceV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    @using_valuation_context
    def evidence_matches_policy(self) -> MarketPolicyInputsV1:
        evidence_by_role = {item.role: item for item in self.evidence}
        if len(evidence_by_role) != len(self.evidence):
            raise ValueError("market policy evidence roles must be unique")
        required = {
            "risk_free_rate": self.risk_free_rate,
            "beta": self.beta,
            "equity_risk_premium": self.equity_risk_premium,
            "pre_tax_cost_of_debt": self.pre_tax_cost_of_debt,
            "debt_weight": self.debt_weight,
            "equity_weight": self.equity_weight,
            "terminal_growth": self.terminal_growth,
        }
        missing = tuple(role for role in required if role not in evidence_by_role)
        if missing:
            raise ValueError(
                "market policy evidence is missing required roles: "
                + ", ".join(missing)
            )
        mismatched = tuple(
            role
            for role, value in required.items()
            if evidence_by_role[role].value != value
        )
        if mismatched:
            raise ValueError(
                "market policy evidence values do not match policy: "
                + ", ".join(mismatched)
            )
        if self.debt_weight + self.equity_weight != Decimal("1"):
            raise ValueError("market policy weights must sum to one")
        if not all(
            Decimal("0") <= value <= Decimal("1")
            for value in (self.debt_weight, self.equity_weight)
        ):
            raise ValueError("market policy weights must be between zero and one")
        weight_methods = {
            evidence_by_role[role].method for role in ("debt_weight", "equity_weight")
        }
        if self.capital_weight_basis == "market_observed" and weight_methods != {
            "observed_source"
        }:
            raise ValueError(
                "market-observed capital weights require observed-source evidence"
            )
        if self.capital_weight_basis == "approved_policy" and weight_methods != {
            "approved_policy"
        }:
            raise ValueError(
                "approved-policy capital weights require approved-policy evidence"
            )
        if self.terminal_growth >= Decimal("1"):
            raise ValueError("terminal growth must be below 100 percent")
        return self


class IdentityV1(StrictModel):
    issuer_id: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    domicile: str = Field(min_length=2, max_length=2)
    reporting_basis: Literal["us-gaap", "ifrs"]
    security_id: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


class IdentityResolutionRequestV1(StrictModel):
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class IdentitySourceEvidenceV1(StrictModel):
    source_id: Literal["sec-company-tickers", "sec-submissions", "sec-companyfacts"]
    source_uri: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    available_at: datetime
    media_type: Literal["application/json"]
    byte_count: int = Field(ge=0)

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> IdentitySourceEvidenceV1:
        for name, value in (
            ("captured_at", self.captured_at),
            ("available_at", self.available_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        return self


class IdentityResolutionV1(StrictModel):
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    identity: IdentityV1
    mapping_version: Literal["sec-issuer-identity-v1"]
    source_evidence: tuple[IdentitySourceEvidenceV1, ...] = Field(
        min_length=3, max_length=3
    )
    resolution_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def resolution_is_bound_to_evidence(self) -> IdentityResolutionV1:
        expected_sources = {
            "sec-company-tickers",
            "sec-submissions",
            "sec-companyfacts",
        }
        source_ids = {source.source_id for source in self.source_evidence}
        if source_ids != expected_sources:
            raise ValueError("identity resolution requires all SEC source evidence")
        if self.identity.security_id != self.ticker:
            raise ValueError("identity security_id must retain the selected ticker")
        if self.identity.share_class != self.ticker:
            raise ValueError("identity share_class must use the opaque ticker key")
        expected_digest = sha256_digest(
            self.model_dump(mode="json", exclude={"resolution_digest"})
        )
        if self.resolution_digest != expected_digest:
            raise ValueError("resolution_digest does not bind identity evidence")
        return self


class FiscalPeriodV1(StrictModel):
    """One issuer fiscal year selected by the caller."""

    fiscal_year: int = Field(ge=1900, le=2200)


class FiscalPeriodSelectorV1(StrictModel):
    """Versioned caller-owned fiscal-period selection policy."""

    version: Literal["fundamental.fiscal-period-selector.v1"] = (
        "fundamental.fiscal-period-selector.v1"
    )
    mode: Literal["latest_complete", "explicit_periods"]
    count: int | None = Field(default=None, ge=1, le=10)
    periods: tuple[FiscalPeriodV1, ...] = ()

    @field_validator("periods", mode="before")
    @classmethod
    def normalize_periods(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def selector_shape(self) -> FiscalPeriodSelectorV1:
        if self.mode == "latest_complete":
            if self.count is None:
                object.__setattr__(self, "count", 3)
            if self.periods:
                raise ValueError("latest_complete selector cannot include periods")
        elif self.count is not None:
            raise ValueError("explicit_periods selector cannot include count")
        elif not self.periods:
            raise ValueError("explicit_periods selector requires periods")
        years = tuple(period.fiscal_year for period in self.periods)
        if len(years) != len(set(years)):
            raise ValueError("fiscal periods must be unique")
        return self


class ResolvedFiscalPeriodV1(StrictModel):
    fiscal_year: int = Field(ge=1900, le=2200)
    period_start: date
    period_end: date
    available_at: datetime

    @model_validator(mode="after")
    def period_is_valid(self) -> ResolvedFiscalPeriodV1:
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must include a timezone")
        return self


class FiscalPeriodResolutionV1(StrictModel):
    status: Literal["resolved", "degraded", "abstained", "unavailable"]
    selector: FiscalPeriodSelectorV1
    requested_fiscal_years: tuple[int, ...] = Field(min_length=1)
    resolved_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    missing_fiscal_years: tuple[int, ...] = ()
    issue_codes: tuple[str, ...] = ()


class DimensionV1(StrictModel):
    name: str = Field(min_length=1)
    member: str = Field(min_length=1)


class XbrlContextV1(StrictModel):
    concept_qname: str = Field(min_length=1)
    period_type: PeriodType
    start_date: date | None = None
    end_date: date | None = None
    instant: date | None = None
    unit_qname: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    dimensions: tuple[DimensionV1, ...] = ()
    entity_scope: str = Field(min_length=1)
    consolidation_scope: str = Field(min_length=1)
    context_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def period_shape(self) -> XbrlContextV1:
        if self.period_type is PeriodType.INSTANT and self.instant is None:
            raise ValueError("instant context requires instant")
        if self.period_type is PeriodType.DURATION and (
            self.start_date is None or self.end_date is None
        ):
            raise ValueError("duration context requires start_date and end_date")
        if self.period_type is PeriodType.INSTANT and (
            self.start_date or self.end_date
        ):
            raise ValueError("instant context cannot include duration dates")
        return self


class SourceRecordV1(StrictModel):
    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    role: SourceRole
    available_at: datetime
    captured_at: datetime
    publication_at: datetime | None = None
    http_status: int = Field(ge=100, le=599)
    media_type: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1)
    accession_number: str | None = None
    form: str | None = None
    filing_date: date | None = None
    filed_at: datetime | None = None
    filing_version: str | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    taxonomy_manifest_id: str | None = None
    response_headers: tuple[tuple[str, str], ...] = ()
    declared_size: int | None = Field(default=None, ge=0)
    received_size: int | None = Field(default=None, ge=0)
    # Retained so manifests written before SourceRole.ACQUISITION remain readable.
    # New snapshots use the role as the authoritative source classification.
    point_in_time_relevant: bool = True

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> SourceRecordV1:
        for name, value in (
            ("available_at", self.available_at),
            ("captured_at", self.captured_at),
            ("publication_at", self.publication_at),
            ("filed_at", self.filed_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        return self


class RemovedByteRangeV1(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_range(self) -> RemovedByteRangeV1:
        if self.end <= self.start:
            raise ValueError("removed byte range must be non-empty")
        return self


class ArelleFindingEvidenceV1(StrictModel):
    code: str = Field(min_length=1)
    severity: Literal["warning", "error", "critical", "fatal"]
    blocks: bool
    rule_severity: Literal["warning", "error", "critical", "fatal"] | None = None


class SecIntegrityEvidenceV1(StrictModel):
    """Reproducible link from SEC response bytes to parser and fact evidence."""

    accession_number: str = Field(min_length=1)
    primary_document_uri: str = Field(min_length=1)
    captured_at: datetime
    archive_index_uri: str = Field(min_length=1)
    archive_index_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_primary_size: int = Field(ge=0)
    raw_response_headers: tuple[tuple[str, str], ...] = ()
    raw_received_size: int = Field(ge=0)
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_response_size: int | None = Field(default=None, ge=0)
    archive_uri: str = Field(min_length=1)
    archive_size: int = Field(ge=0)
    archive_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_member_name: str = Field(min_length=1)
    archive_member_size: int = Field(ge=0)
    archive_member_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrity_relation: Literal["exact", "normalized"]
    normalized_content_size: int = Field(ge=0)
    normalized_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalization_policy_id: str | None = None
    normalization_rule_signature: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    normalization_reason: str | None = None
    removed_ranges: tuple[RemovedByteRangeV1, ...] = ()
    normalized_fact_count: int = Field(ge=0)
    normalized_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_fact_count: int = Field(ge=0)
    archive_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_engines: tuple[str, ...] = ()
    validation_evidence: tuple[str, ...] = ()
    network_attempt_count: int = Field(ge=0)
    taxonomy_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    arelle_version: str = Field(min_length=1)
    efm_profile: str = Field(min_length=1)
    dqc_version: str = Field(min_length=1)
    xule_version: str = Field(min_length=1)
    findings: tuple[ArelleFindingEvidenceV1, ...] = ()
    quality_decision: Literal["pass", "block"]

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> SecIntegrityEvidenceV1:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        if self.parser_input_hash != self.normalized_content_hash:
            raise ValueError("parser input hash must match normalized source hash")
        if self.network_attempt_count != 0:
            raise ValueError("offline SEC validation cannot contain network attempts")
        if not {"sec-efm", "dqc-us"}.issubset(self.validation_engines):
            raise ValueError("SEC integrity evidence requires EFM and DQC engines")
        if not {
            "strict-sec-efm-profile-selected",
            {
                V1_PROFILE.dqc_version: V1_PROFILE.completion_marker,
                V3_PROFILE.dqc_version: V3_PROFILE.completion_marker,
            }.get(self.dqc_version, "dqc-dqcrt-checks-completed"),
        }.issubset(self.validation_evidence):
            raise ValueError("SEC integrity evidence requires EFM and DQC evidence")
        if self.normalized_fact_count != self.archive_fact_count:
            raise ValueError("normalized and archive fact counts must match")
        if self.normalized_fact_digest != self.archive_fact_digest:
            raise ValueError("normalized and archive fact digests must match")
        if self.quality_decision == "pass" and any(
            finding.blocks for finding in self.findings
        ):
            raise ValueError("blocking findings cannot have a passing decision")
        if self.integrity_relation == "exact" and self.removed_ranges:
            raise ValueError("exact integrity cannot contain removed byte ranges")
        if self.integrity_relation == "normalized" and (
            not self.normalization_policy_id or not self.normalization_rule_signature
        ):
            raise ValueError("normalized integrity requires a signed policy")
        return self


class SecHistoryComponentV1(StrictModel):
    """An immutable original snapshot and its own parser-bound integrity."""

    snapshot_id: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrity: SecIntegrityEvidenceV1


class SecHistoryIntegrityEvidenceV1(StrictModel):
    """Evidence for a composition of independently validated original filings."""

    protocol: Literal["sec-original-history-v1"] = "sec-original-history-v1"
    components: tuple[SecHistoryComponentV1, ...] = Field(min_length=2, max_length=6)
    quality_decision: Literal["pass"] = "pass"

    @model_validator(mode="after")
    def original_components_are_unique(self) -> SecHistoryIntegrityEvidenceV1:
        ids = tuple(component.snapshot_id for component in self.components)
        accessions = tuple(
            component.integrity.accession_number for component in self.components
        )
        if ids != tuple(sorted(set(ids))) or len(accessions) != len(set(accessions)):
            raise ValueError(
                "history components must be sorted, unique original snapshots"
            )
        if any(
            component.integrity.quality_decision != "pass"
            for component in self.components
        ):
            raise ValueError("every history original must pass its own integrity gates")
        return self


class SecCapturedSourceEvidenceV1(StrictModel):
    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    role: SourceRole
    media_type: str = Field(min_length=1)
    http_status: int = Field(ge=100, le=599)
    available_at: datetime
    captured_at: datetime
    publication_at: datetime | None = None
    accession_number: str | None = None
    form: str | None = None
    filed_at: datetime | None = None
    response_headers: tuple[tuple[str, str], ...] = ()
    declared_size: int | None = Field(default=None, ge=0)
    received_size: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> SecCapturedSourceEvidenceV1:
        for name, value in (
            ("available_at", self.available_at),
            ("captured_at", self.captured_at),
            ("publication_at", self.publication_at),
            ("filed_at", self.filed_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        return self


class SecIngestionRejectionEvidenceV1(StrictModel):
    contract_version: Literal["fundamental.sec-ingestion-rejection.v1"]
    error_code: Literal["PARSER_VALIDATION_BLOCKED"]
    captured_sources: tuple[SecCapturedSourceEvidenceV1, ...] = Field(min_length=3)
    integrity_evidence: SecIntegrityEvidenceV1
    parser_replay_digests: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def source_and_parser_evidence_are_bound(self) -> SecIngestionRejectionEvidenceV1:
        evidence = self.integrity_evidence
        if evidence.quality_decision != "block" or not any(
            finding.blocks for finding in evidence.findings
        ):
            raise ValueError("rejection evidence requires a blocking parser finding")
        source_hashes = {
            (source.source_id, source.content_hash) for source in self.captured_sources
        }
        if ("sec-filing", evidence.raw_content_hash) not in source_hashes:
            raise ValueError("rejection evidence must reference the raw filing")
        if ("sec-filing-index", evidence.archive_index_hash) not in source_hashes:
            raise ValueError("rejection evidence must reference the archive index")
        if ("sec-filing-archive", evidence.archive_hash) not in source_hashes:
            raise ValueError("rejection evidence must reference the SEC archive")
        if any(not is_digest(digest) for digest in self.parser_replay_digests):
            raise ValueError("parser replay digests must be SHA-256 values")
        return self


class SourceSnapshotV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    identity: IdentityV1
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    captured_at: datetime
    source_records: tuple[SourceRecordV1, ...] = Field(min_length=1)
    taxonomy_manifest_id: str | None = None
    acquisition_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validation_profile_id: str | None = None
    validation_profile_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    parser_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    coverage_status: QualityStatus
    issues: tuple[IssueV1, ...] = ()
    sec_integrity_evidence: (
        SecIntegrityEvidenceV1 | SecHistoryIntegrityEvidenceV1 | None
    ) = None
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> SourceSnapshotV1:
        payload = self.model_dump(exclude={"manifest_digest", "snapshot_id"})
        if self.manifest_digest == sha256_digest(payload):
            return self

        # Older immutable manifests omit fields added to the strict contract.
        # Validate their digest against only the fields present in stored JSON.
        legacy_payload = self.model_dump(
            exclude={"manifest_digest", "snapshot_id"}, exclude_unset=True
        )
        if self.manifest_digest != sha256_digest(legacy_payload):
            raise ValueError(
                "manifest_digest does not match canonical snapshot manifest"
            )
        return self

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> SourceSnapshotV1:
        for name, value in (
            ("valuation_timestamp", self.valuation_timestamp),
            ("captured_at", self.captured_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if (
            any(record.captured_at > self.captured_at for record in self.source_records)
            and self.coverage_status is QualityStatus.VERIFIED
        ):
            raise ValueError("verified snapshots must cover every source capture time")
        return self

    @model_validator(mode="after")
    def history_integrity_covers_each_original(self) -> SourceSnapshotV1:
        evidence = self.sec_integrity_evidence
        if not isinstance(evidence, SecHistoryIntegrityEvidenceV1):
            return self
        originals = {
            component.integrity.accession_number: component.integrity
            for component in evidence.components
        }
        filing_sources = tuple(
            source for source in self.source_records if source.source_id == "sec-filing"
        )
        if {source.accession_number for source in filing_sources} != set(originals):
            raise ValueError(
                "history must cover exactly the declared original accessions"
            )
        for source in filing_sources:
            if source.accession_number is None:
                raise ValueError("history filing must identify its original accession")
            integrity = originals[source.accession_number]
            if (
                source.content_hash != integrity.raw_content_hash
                or source.parser_input_hash != integrity.parser_input_hash
                or source.uri != integrity.primary_document_uri
                or source.is_amendment
                or source.form != "10-K"
                or source.available_at > self.valuation_timestamp
                or integrity.captured_at > self.captured_at
                or integrity.validation_profile_digest != self.validation_profile_digest
            ):
                raise ValueError(
                    "history filing source differs from its original integrity evidence"
                )
        return self


class SnapshotResolutionRequestV1(StrictModel):
    """Caller-owned point-in-time selector for an immutable data snapshot."""

    contract_version: Literal["fundamental.v1"]
    release_profile_id: str | None = Field(default=None, min_length=1)
    identity: IdentityV1
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1 | None = None
    source_selection_policy: Literal["pit-v1"]
    coverage_profile: str = Field(min_length=1)
    required_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class FactsReadRequestV1(StrictModel):
    """Select canonical facts from one immutable snapshot."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    required_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_fields")
    @classmethod
    def fields_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("required_fields must be unique")
        return value


class SnapshotResolutionV1(StrictModel):
    """Immutable references needed to construct a complete valuation input."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    historical_facts: tuple[str, ...] = Field(min_length=1)
    identity: IdentityV1
    valuation_timestamp: datetime
    snapshot_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    fiscal_period_resolution: FiscalPeriodResolutionV1 | None = None
    source_selection_policy: str = Field(min_length=1)
    coverage_profile: str = Field(min_length=1)
    quality: QualityStatus
    issue_codes: tuple[str, ...] = ()
    provenance: dict[str, object]

    @field_validator("valuation_timestamp", "snapshot_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class MissingValueV1(StrictModel):
    status: Literal["missing", "not_applicable", "unsupported", "unresolved"]
    reason: str = Field(min_length=1)


class CandidateRejectionV1(StrictModel):
    candidate_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CanonicalFactV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    fact_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    security_id: str | None = None
    concept: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    value: Decimal | str | bool | MissingValueV1
    unit: str = Field(min_length=1)
    scale: int
    currency: str | None = None
    period_start: date | None = None
    period_end: date
    instant: date | None = None
    context: XbrlContextV1
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
    source: SourceProvenanceV1
    quality: QualityStatus
    issue_codes: tuple[str, ...] = ()
    mapping_decision_id: str | None = None
    mapping_confidence: Literal["high", "medium", "low", "unresolved"] | None = None
    rejected_candidates: tuple[str, ...] = ()
    rejected_candidate_reasons: tuple[CandidateRejectionV1, ...] = ()
    point_in_time_policy: str | None = None
    selection_reason: str | None = None
    accounting_evidence: AccountingRoleEvidenceV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def point_in_time_order(self) -> CanonicalFactV1:
        evidence = self.accounting_evidence
        if self.concept.startswith("computed:") and evidence is None:
            raise ValueError("computed accounting roles require their source evidence")
        if evidence is not None:
            rules, period = evidence.rule_set, evidence.period_rule.period
            if (
                evidence.value is None
                or self.value != evidence.value
                or self.issuer_id != rules.issuer_id
                or self.security_id != rules.security_id
                or self.normalized_field != rules.normalized_field
                or self.concept != f"computed:{rules.normalized_field}"
                or self.unit != rules.unit
                or self.currency != rules.currency
                or self.period_start != period.period_start
                or self.period_end != period.period_end
                or self.instant != (period.period_end if period.instant else None)
                or self.source.content_hash != rules.raw_content_hash
                or self.source.accession_number != rules.accession_number
                or self.source.available_at != self.available_at
                or self.accession_number != rules.accession_number
                or self.is_amendment
                or self.available_at.date() < period.period_end
                or any(
                    (fact.instant or fact.period_end or period.period_end)
                    > self.available_at.date()
                    for fact in evidence.source_facts
                )
                or self.context.concept_qname != self.concept
                or self.context.unit_qname != self.unit
                or self.context.dimensions
                or self.context.consolidation_scope != "consolidated"
                or self.context.start_date != period.period_start
                or self.context.instant != self.instant
                or self.context.end_date
                != (None if period.instant else period.period_end)
                or self.decimals
                != accounting_reported_decimals(
                    evidence.period_rule, evidence.source_facts
                )
            ):
                raise ValueError(
                    "computed role fact differs from its source-bound accounting evidence"
                )
        for earlier, later, name in (
            (self.available_at, self.captured_at, "available_at/captured_at"),
        ):
            if earlier > later:
                raise ValueError(f"{name} ordering is invalid")
        if self.quality is QualityStatus.VERIFIED and isinstance(
            self.value, MissingValueV1
        ):
            raise ValueError("verified facts cannot contain a missing value")
        return self

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> CanonicalFactV1:
        for name, value in (
            ("as_of", self.as_of),
            ("available_at", self.available_at),
            ("filed_at", self.filed_at),
            ("captured_at", self.captured_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        return self


class FactsReadResponseV1(StrictModel):
    """Point-in-time fact selection and quality metadata for one snapshot."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: IdentityV1
    valuation_timestamp: datetime
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    facts: tuple[CanonicalFactV1, ...] = Field(min_length=1)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class ValuationEvidenceReadRequestV1(StrictModel):
    """Read exact release-bound facts for one service-owned valuation profile."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: InitialModelId


class ValuationEvidenceReadResponseV1(StrictModel):
    """Profile-bound fact evidence, including explicit missing/rejected roles."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: IdentityV1
    valuation_timestamp: datetime
    model_id: InitialModelId
    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    rejected_fact_ids: tuple[str, ...] = ()
    mapping_version: str | None = Field(default=None, min_length=1)
    facts: tuple[CanonicalFactV1, ...] = ()

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class SecFilingSelectorV1(StrictModel):
    """Bounded SEC filing selection; callers never supply provider URLs."""

    accession_number: str | None = Field(default=None, pattern=r"^\d{10}-\d{2}-\d{6}$")
    forms: tuple[Literal["10-K", "10-K/A", "10-Q", "10-Q/A"], ...] = (
        "10-K",
        "10-Q",
    )
    lookback_days: int = Field(default=3650, ge=1, le=3650)

    @field_validator("forms")
    @classmethod
    def forms_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("forms must be non-empty and unique")
        return value


class SecMappingReferenceV1(StrictModel):
    decision_id: str = Field(min_length=1, max_length=128)
    mapping_version: str = Field(min_length=1, max_length=128)
    normalized_field: str = Field(min_length=1, max_length=128)


SecIdentityBasis = Literal["current-sec-ticker-v1", "original-filing-dei-v1"]


class SecIngestionRequestV1(StrictModel):
    """Versioned, service-owned request for bounded SEC filing acquisition."""

    contract_version: Literal["fundamental.v1"]
    identity: IdentityV1
    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
    identity_basis: SecIdentityBasis = "current-sec-ticker-v1"
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    # Transition FCFF includes the base evidence set plus filed operating
    # evidence, so the canonical request must accept more than 32 fields.
    required_fields: tuple[str, ...] = Field(min_length=1, max_length=64)
    mappings: tuple[SecMappingReferenceV1, ...] = Field(min_length=1, max_length=64)
    source_selection_policy: Literal["sec-pit-v1"]
    coverage_profile: str = Field(min_length=1, max_length=128)
    legal_use_profile: Literal["sec-public-us-v1"]
    filing: SecFilingSelectorV1
    parser_version: Literal["2.47.4"]
    validation_profile_id: Literal[
        "sec-efm-us-dqc-v31.0.3", "sec-efm-us-dqc-v1.0.0-historical"
    ]
    taxonomy_manifest_id: str = Field(min_length=1, max_length=128)
    taxonomy_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)

    @field_validator("valuation_timestamp")
    @classmethod
    def valuation_timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def request_is_canonical(self) -> "SecIngestionRequestV1":
        if self.identity_basis == "original-filing-dei-v1" and (
            self.filing.accession_number is None or self.filing.forms != ("10-K",)
        ):
            raise ValueError("original filing identity requires a pinned original 10-K")
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError("required_fields must be unique")
        if set(self.required_fields) != {
            item.normalized_field for item in self.mappings
        }:
            raise ValueError("each required field needs exactly one mapping")
        if len({item.normalized_field for item in self.mappings}) != len(self.mappings):
            raise ValueError("mappings must contain one reference per field")
        normalized_cik = str(int(self.cik))
        normalized_issuer = self.identity.issuer_id.lstrip("0") or "0"
        if not self.identity.issuer_id.isdigit() or normalized_issuer != normalized_cik:
            raise ValueError("CIK must match the canonical issuer identity")
        if self.identity.domicile != "US":
            raise ValueError("SEC ingestion requires a US issuer identity")
        return self


class SecIngestionSourceV1(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2048)
    role: SourceRole
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    accession_number: str | None = None
    available_at: datetime
    captured_at: datetime
    filed_at: datetime | None = None


class SecIngestionResponseV1(StrictModel):
    """Typed references for a created or reused immutable SEC snapshot."""

    contract_version: Literal["fundamental.v1"]
    status: Literal["created", "reused", "degraded", "abstain"]
    identity: IdentityV1
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    snapshot_id: str | None = None
    manifest_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    canonical_fact_ids: tuple[str, ...] = ()
    source_evidence: tuple[SecIngestionSourceV1, ...] = ()
    identity_evidence_ref: str | None = Field(default=None, min_length=1)
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    parser_version: str = Field(min_length=1)
    validation_profile_id: str = Field(min_length=1)
    validation_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_manifest_id: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    reused: bool = False
    coalesced: bool = False
    correlation_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def snapshot_reference_is_complete(self) -> "SecIngestionResponseV1":
        if (self.snapshot_id is None) != (self.manifest_digest is None):
            raise ValueError("snapshot_id and manifest_digest must be paired")
        if self.status != "abstain" and self.snapshot_id is None:
            raise ValueError("successful ingestion requires an immutable snapshot")
        if self.reused != (self.status == "reused"):
            raise ValueError("reused flag must match ingestion status")
        return self

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class ForecastAssumptionsV1(StrictModel):
    base_revenue: Decimal | None = None
    revenue_growth: tuple[Decimal, ...] = Field(min_length=1)
    operating_margin: tuple[Decimal, ...] = Field(min_length=1)
    reinvestment_rate: tuple[Decimal, ...] = Field(min_length=1)


class WaccAssumptionsV1(StrictModel):
    risk_free_rate: Decimal
    beta: Decimal
    equity_risk_premium: Decimal
    pre_tax_cost_of_debt: Decimal
    tax_rate: Decimal
    debt_weight: Decimal
    equity_weight: Decimal

    @model_validator(mode="after")
    @using_valuation_context
    def weights_and_rates(self) -> WaccAssumptionsV1:
        if self.equity_weight + self.debt_weight != Decimal("1"):
            raise ValueError("debt_weight and equity_weight must sum to 1")
        return self


class CapitalBridgeAssumptionsV1(StrictModel):
    cash: Decimal
    debt: Decimal
    preferred_stock: Decimal
    lease_liabilities: Decimal
    non_controlling_interest: Decimal
    diluted_shares: Decimal = Field(gt=0)


class BankAssumptionsV1(StrictModel):
    """Caller-owned inputs for a regulatory-capital constrained bank model."""

    current_book_value: Decimal = Field(gt=0)
    tangible_book_value: Decimal = Field(gt=0)
    forecast_net_income: tuple[Decimal, ...] = Field(min_length=3, max_length=10)
    forecast_rwa_growth: tuple[Decimal, ...] = Field(min_length=3, max_length=10)
    cost_of_equity: Decimal = Field(gt=0)
    payout_ratio: Decimal = Field(ge=0, le=1)
    terminal_growth: Decimal = Field(ge=0)
    reported_rwa: Decimal = Field(gt=0)
    cet1_capital: Decimal = Field(gt=0)
    minimum_cet1_ratio: Decimal = Field(gt=0, le=1)
    fdic_certificate: str = Field(min_length=1)
    reporting_entity_relationship: Literal[
        "same_legal_entity", "consolidated_subsidiary"
    ]
    fact_references: dict[BankFactField, str]
    diluted_shares: Decimal = Field(gt=0)
    trace: TraceV1

    @property
    @using_valuation_context
    def cet1_ratio(self) -> Decimal:
        return self.cet1_capital / self.reported_rwa

    @model_validator(mode="after")
    @using_valuation_context
    def regulatory_constraints(self) -> BankAssumptionsV1:
        if self.cet1_capital / self.reported_rwa < self.minimum_cet1_ratio:
            raise ValueError("reported CET1 ratio is below the model minimum")
        if self.terminal_growth >= self.cost_of_equity:
            raise ValueError("terminal growth must be below cost of equity")
        if len(self.forecast_net_income) != len(self.forecast_rwa_growth):
            raise ValueError("bank income and RWA forecasts must have equal length")
        if any(value <= Decimal("-1") for value in self.forecast_rwa_growth):
            raise ValueError("forecast RWA growth must exceed -100 percent")
        if self.tangible_book_value > self.current_book_value:
            raise ValueError("tangible book value cannot exceed reported book value")
        required_references = {
            "current_book_value",
            "tangible_book_value",
            "reported_rwa",
            "cet1_capital",
            "diluted_shares",
            "regulatory_entity",
            "issuer_entity_relationship",
        }
        if set(self.fact_references) != required_references:
            raise ValueError("bank fact references must cover every reported input")
        if any(not fact_id for fact_id in self.fact_references.values()):
            raise ValueError("bank fact references cannot be empty")
        return self


class AssumptionsV1(StrictModel):
    forecast: ForecastAssumptionsV1 | None = None
    wacc: WaccAssumptionsV1 | None = None
    terminal_growth: Decimal | None = None
    capital_bridge: CapitalBridgeAssumptionsV1 | None = None
    trace: TraceV1 | None = None
    bank: BankAssumptionsV1 | None = None


def _valuation_input_json_schema(schema: dict[str, Any]) -> None:
    fcff_fields = ("forecast", "wacc", "terminal_growth", "capital_bridge", "trace")
    schema.setdefault("allOf", []).extend(
        [
            {
                "if": {
                    "properties": {"model_id": {"const": "bank_excess_return"}},
                    "required": ["model_id"],
                },
                "then": {
                    "properties": {
                        "assumptions": {
                            "required": ["bank"],
                            "properties": {
                                "bank": {"not": {"type": "null"}},
                                **{field: {"type": "null"} for field in fcff_fields},
                            },
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "model_id": {"enum": ["fcff_dcf", "transition_fcff_dcf"]}
                    },
                    "required": ["model_id"],
                },
                "then": {
                    "properties": {
                        "assumptions": {
                            "required": list(fcff_fields),
                            "properties": {
                                **{
                                    field: {"not": {"type": "null"}}
                                    for field in fcff_fields
                                },
                                "bank": {"type": "null"},
                            },
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "model_id": {
                            "enum": [
                                "fcff_dcf",
                                "transition_fcff_dcf",
                                "insurance_statutory_excess_return",
                                "reit_nav",
                                "regulated_utility",
                                "normalized_cyclical",
                                "biotech_rnpv",
                                "sum_of_parts",
                                "ifrs_fcff_dcf",
                            ]
                        }
                    },
                    "required": ["model_id"],
                },
                "then": {
                    "properties": {
                        "assumptions": {"properties": {"bank": {"type": "null"}}}
                    }
                },
            },
        ]
    )


class DistributionProvenanceV1(StrictModel):
    """Source evidence for one service-owned uncertainty distribution."""

    source_kind: Literal["empirical_history", "policy_prior"]
    historical_periods: tuple[int, ...] = ()
    source_fact_ids: tuple[str, ...] = ()
    estimation_method: str = Field(min_length=1)
    policy_version: str | None = Field(default=None, min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def source_requirements(self) -> DistributionProvenanceV1:
        if self.source_kind == "empirical_history":
            if not self.historical_periods or not self.source_fact_ids:
                raise ValueError(
                    "empirical distributions require historical periods and source facts"
                )
        if self.source_kind == "policy_prior" and self.policy_version is None:
            raise ValueError("policy priors require a policy version")
        return self


class DistributionParameterV1(StrictModel):
    path: str = Field(min_length=1)
    distribution: Literal["normal", "lognormal", "uniform", "triangular"]
    lower: Decimal
    upper: Decimal
    mode: Decimal | None = None
    mean: Decimal | None = None
    provenance: DistributionProvenanceV1 | None = None

    @model_validator(mode="after")
    def bounds(self) -> DistributionParameterV1:
        if self.lower > self.upper:
            raise ValueError("distribution lower bound exceeds upper bound")
        if self.mode is not None and not self.lower <= self.mode <= self.upper:
            raise ValueError("distribution mode is outside bounds")
        if self.mean is not None and not self.lower <= self.mean <= self.upper:
            raise ValueError("distribution mean is outside bounds")
        if self.distribution in {"normal", "lognormal"} and self.mean is None:
            raise ValueError(f"{self.distribution} distribution requires mean")
        if self.distribution == "triangular" and self.mode is None:
            raise ValueError("triangular distribution requires mode")
        if self.distribution == "uniform" and (
            self.mean is not None or self.mode is not None
        ):
            raise ValueError("uniform distribution does not accept mean or mode")
        return self


class ScenarioInputV1(StrictModel):
    name: Literal["base", "downside", "upside"]
    assumptions: dict[str, object] = {}


class SensitivityInputV1(StrictModel):
    path: str = Field(min_length=1)
    values: tuple[object, ...] = Field(min_length=2)


class UncertaintyV1(StrictModel):
    mode: Literal["none", "scenarios", "monte_carlo"]
    parameters: tuple[DistributionParameterV1, ...] = ()
    samples: int | None = Field(default=None, ge=1, le=1_000_000)
    seed: int | None = None
    policy_version: str | None = Field(default=None, min_length=1)
    correlations: tuple[tuple[str, str, Decimal], ...] = ()
    invalid_draw_policy: Literal["reject", "skip", "abstain"] | None = None
    scenarios: tuple[ScenarioInputV1, ...] = ()
    sensitivity: tuple[SensitivityInputV1, ...] = ()

    @model_validator(mode="after")
    def sampling_requirements(self) -> UncertaintyV1:
        if self.mode == "monte_carlo" and (
            not self.parameters
            or self.samples is None
            or self.seed is None
            or self.invalid_draw_policy is None
        ):
            raise ValueError(
                "monte_carlo requires parameters, samples, seed, "
                "and invalid_draw_policy"
            )
        if self.mode == "monte_carlo" and self.policy_version is not None:
            if any(parameter.provenance is None for parameter in self.parameters):
                raise ValueError(
                    "versioned Monte Carlo policies require distribution provenance"
                )
        paths = {parameter.path for parameter in self.parameters}
        if len(paths) != len(self.parameters):
            raise ValueError("uncertainty parameter paths must be unique")
        for parameter in self.parameters:
            if not parameter.path.startswith("assumptions."):
                raise ValueError("uncertainty paths must target assumptions")
        for left, right, correlation in self.correlations:
            if left == right or left not in paths or right not in paths:
                raise ValueError("correlations must reference distinct parameter paths")
            if not Decimal("-1") <= correlation <= Decimal("1"):
                raise ValueError("correlations must be between -1 and 1")
        if self.mode == "none" and (
            self.parameters
            or self.samples is not None
            or self.seed is not None
            or self.policy_version is not None
            or self.correlations
            or self.invalid_draw_policy is not None
            or self.scenarios
            or self.sensitivity
        ):
            raise ValueError("mode none cannot include uncertainty controls")
        if self.mode == "scenarios" and (
            self.parameters
            or self.samples is not None
            or self.seed is not None
            or self.policy_version is not None
            or self.correlations
            or self.invalid_draw_policy is not None
        ):
            raise ValueError("scenarios mode cannot include Monte Carlo controls")
        return self


class QualityInputV1(StrictModel):
    status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class ValuationContextV1(StrictModel):
    valuation_timestamp: datetime
    data_snapshot_id: str = Field(min_length=1)
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    source_selection_policy: str = Field(min_length=1)
    coverage_profile: str = Field(min_length=1)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class ProvenanceInputV1(StrictModel):
    snapshot_id: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = ()
    fiscal_period_selector: FiscalPeriodSelectorV1 = FiscalPeriodSelectorV1(
        mode="latest_complete", count=3
    )
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    mapping_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    policy_version: str | None = None
    preparation_version: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    equity_dilution_evidence_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", exclude_if=lambda value: value is None
    )


class CallerApprovalEnvelopeV1(StrictModel):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved", "rejected"]
    caller_id: str = Field(min_length=1)
    decided_at: datetime


class ValuationInputV1(StrictModel):
    model_config = ConfigDict(json_schema_extra=_valuation_input_json_schema)

    contract_version: Literal["fundamental.v1"]
    identity: IdentityV1
    valuation_context: ValuationContextV1
    historical_facts: tuple[str, ...] = Field(min_length=1)
    assumptions: AssumptionsV1
    uncertainty: UncertaintyV1
    quality: QualityInputV1
    provenance: ProvenanceInputV1
    model_id: ModelId
    model_version: str = Field(min_length=1)
    policy_id: str | None = None
    input_digest: str | None = None
    caller_approval: CallerApprovalEnvelopeV1 | None = None

    @model_validator(mode="after")
    def model_assumptions_present(self) -> ValuationInputV1:
        if self.model_id == "bank_excess_return":
            if self.assumptions.bank is None:
                raise ValueError("bank_excess_return requires assumptions.bank")
            if any(
                value is not None
                for value in (
                    self.assumptions.forecast,
                    self.assumptions.wacc,
                    self.assumptions.terminal_growth,
                    self.assumptions.capital_bridge,
                    self.assumptions.trace,
                )
            ):
                raise ValueError(
                    "bank_excess_return must not include FCFF-specific assumptions"
                )
            if not set(self.assumptions.bank.fact_references.values()) <= set(
                self.historical_facts
            ):
                raise ValueError("bank fact references must belong to historical_facts")
        elif self.model_id in {"fcff_dcf", "transition_fcff_dcf"} and (
            any(
                value is None
                for value in (
                    self.assumptions.forecast,
                    self.assumptions.wacc,
                    self.assumptions.terminal_growth,
                    self.assumptions.capital_bridge,
                    self.assumptions.trace,
                )
            )
            or self.assumptions.bank is not None
        ):
            raise ValueError("FCFF models require FCFF assumptions only")
        elif self.model_id not in {"fcff_dcf", "transition_fcff_dcf"} and (
            self.assumptions.bank is not None
        ):
            raise ValueError("bank assumptions require bank_excess_return")
        return self

    @model_validator(mode="after")
    def digest_and_approval(self) -> ValuationInputV1:
        payload = self.model_dump(exclude={"input_digest", "caller_approval"})
        computed = sha256_digest(payload)
        if self.input_digest is not None and (
            not is_digest(self.input_digest) or self.input_digest != computed
        ):
            raise ValueError("input_digest does not match canonical valuation input")
        if (
            self.caller_approval is not None
            and self.caller_approval.input_digest != computed
        ):
            raise ValueError("caller approval is bound to a different input_digest")
        return self

    def with_digest(self) -> ValuationInputV1:
        digest = sha256_digest(
            self.model_dump(exclude={"input_digest", "caller_approval"})
        )
        return self.model_copy(update={"input_digest": digest})


class ForecastAssumptionOverridesV1(StrictModel):
    base_revenue: Decimal | None = None
    revenue_growth: tuple[Decimal, ...] | None = None
    operating_margin: tuple[Decimal, ...] | None = None
    reinvestment_rate: tuple[Decimal, ...] | None = None


class WaccAssumptionOverridesV1(StrictModel):
    risk_free_rate: Decimal | None = None
    beta: Decimal | None = None
    equity_risk_premium: Decimal | None = None
    pre_tax_cost_of_debt: Decimal | None = None
    tax_rate: Decimal | None = None
    debt_weight: Decimal | None = None
    equity_weight: Decimal | None = None


class CapitalBridgeAssumptionOverridesV1(StrictModel):
    cash: Decimal | None = None
    debt: Decimal | None = None
    preferred_stock: Decimal | None = None
    lease_liabilities: Decimal | None = None
    non_controlling_interest: Decimal | None = None
    diluted_shares: Decimal | None = Field(default=None, gt=0)


class PolicyAssumptionOverridesV1(StrictModel):
    """Explicit caller values; absent fields may be resolved by a pinned policy."""

    forecast: ForecastAssumptionOverridesV1 | None = None
    wacc: WaccAssumptionOverridesV1 | None = None
    terminal_growth: Decimal | None = None
    capital_bridge: CapitalBridgeAssumptionOverridesV1 | None = None
    trace: TraceV1 | None = None
    bank: BankAssumptionsV1 | None = None


class PolicyValuationInputV1(StrictModel):
    """Stateless calculation input with a pinned policy and caller overrides."""

    contract_version: Literal["fundamental.v1"]
    identity: IdentityV1
    valuation_context: ValuationContextV1
    historical_facts: tuple[str, ...] = Field(min_length=1)
    assumptions: PolicyAssumptionOverridesV1
    uncertainty: UncertaintyV1
    quality: QualityInputV1
    provenance: ProvenanceInputV1
    model_id: ModelId
    model_version: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    input_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    caller_approval: CallerApprovalEnvelopeV1 | None = None


class ValidationResponseV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    input: ValuationInputV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: QualityStatus
    policy_resolution: PolicyResolutionV1
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class PolicyResolutionV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_mode: Literal["pinned", "exploratory_active"]
    resolved_fields: dict[str, Any]
    precedence: dict[str, Literal["caller", "policy"]]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class EligibilityReportV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    status: QualityStatus
    selected_model: str | None = None
    candidates: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    forbidden_conditions: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)


class CalculationNodeV1(StrictModel):
    node_id: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    inputs: tuple[str, ...] = ()
    value: Decimal | None = None
    unit: str = Field(min_length=1)
    trace: TraceV1


class ArtifactReferenceV1(StrictModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: Literal["calculation_evidence", "uncertainty_evidence"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["application/json"] = "application/json"


class CalculationTraceV1(StrictModel):
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1
    resolved_fiscal_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
    source_selection_policy: str = Field(min_length=1)
    source_selection_policy_version: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    fact_ids: tuple[str, ...] = Field(min_length=1)
    source_content_hashes: tuple[str, ...] = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    assumptions_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_version: str = Field(min_length=1)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class CalculationArtifactV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    calculation_version: str = Field(min_length=1)
    calculation_status: CalculationStatus
    quality_status: QualityStatus
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intrinsic_value: Decimal | None = None
    per_share_value: Decimal | None = None
    nodes: tuple[CalculationNodeV1, ...] = ()
    assumptions: AssumptionsV1
    policy_id: str | None = None
    model_version: str = Field(min_length=1)
    policy_version: str | None = None
    policy_resolution: PolicyResolutionV1 | None = None
    trace: CalculationTraceV1 | None = None
    artifact_references: tuple[ArtifactReferenceV1, ...] = ()
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    snapshot_id: str = Field(min_length=1)
    valuation_timestamp: datetime
    evaluated_at: datetime
    correlation_id: str = Field(min_length=1)

    @field_validator("valuation_timestamp", "evaluated_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calculation timestamps must include a timezone")
        return value


class CalculationEvidenceV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    request: ValuationInputV1
    calculation: CalculationArtifactV1

    @model_validator(mode="after")
    def evidence_is_digest_bound(self) -> CalculationEvidenceV1:
        calculation = self.calculation
        trace = calculation.trace
        if trace is None:
            raise ValueError("calculation evidence requires a complete trace")
        if self.request.caller_approval is not None:
            raise ValueError("caller approval evidence must not be persisted")
        if (
            calculation.input_digest != self.request.input_digest
            or calculation.snapshot_id != trace.snapshot_id
            or self.request.valuation_context.data_release_manifest_digest
            != trace.data_release_manifest_digest
            or calculation.policy_id != trace.policy_id
            or calculation.policy_version != trace.policy_version
            or calculation.model_version != trace.model_version
            or self.request.policy_id != trace.policy_id
            or self.request.provenance.policy_version != trace.policy_version
            or self.request.model_id != trace.model_id
            or self.request.model_version != trace.model_version
            or self.request.valuation_context.data_snapshot_id != trace.snapshot_id
            or tuple(sorted(self.request.historical_facts)) != trace.fact_ids
            or self.request.provenance.snapshot_id != trace.snapshot_id
            or calculation.policy_resolution is None
            or calculation.policy_resolution.policy_id != trace.policy_id
            or calculation.policy_resolution.policy_version != trace.policy_version
            or calculation.policy_resolution.policy_digest != trace.policy_digest
        ):
            raise ValueError(
                "calculation evidence provenance does not match its request"
            )
        return self


class ArtifactReplayRequestV1(StrictModel):
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReleaseManifestV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    release_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    service_version: str = Field(min_length=1)
    decision_timestamp: datetime
    issuer_id: str = Field(min_length=1)
    security_id: str = Field(min_length=1)
    snapshot_ids: tuple[str, ...] = Field(min_length=1)
    input_hashes: tuple[str, ...] = Field(min_length=1)
    canonical_fact_ids: tuple[str, ...] = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    calibration_artifact_ids: tuple[str, ...] = Field(min_length=1)
    policy_versions: tuple[str, ...] = ()
    model_versions: tuple[str, ...] = ()
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    quality_policy_version: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    calculation_version: str = Field(min_length=1)
    source_content_hashes: tuple[str, ...] = Field(min_length=1)
    random_seed: int | None = None
    numerical_settings: dict[str, str] = Field(min_length=1)
    quality_issue_codes: tuple[str, ...] = ()
    release_profile_thresholds: dict[str, str] = Field(min_length=1)
    artifact_hashes: tuple[str, ...] = Field(min_length=1)
    artifact_ids: tuple[str, ...] = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("decision_timestamp")
    @classmethod
    def decision_timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("decision_timestamp must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator(
        "input_hashes",
        "source_content_hashes",
        mode="before",
    )
    @classmethod
    def normalize_hashes(cls, value: object) -> tuple[str, ...]:
        values = _MANIFEST_STRINGS.validate_python(value or ())
        if any(not is_digest(item) for item in values):
            raise ValueError("manifest hash fields must contain SHA-256 digests")
        return tuple(sorted(set(values)))

    @field_validator("artifact_hashes", mode="before")
    @classmethod
    def preserve_artifact_hash_order(cls, value: object) -> tuple[str, ...]:
        values = _MANIFEST_STRINGS.validate_python(value or ())
        if any(not is_digest(item) for item in values):
            raise ValueError("manifest hash fields must contain SHA-256 digests")
        if len(values) != len(set(values)):
            raise ValueError("artifact_hashes must be unique")
        return values

    @field_validator(
        "snapshot_ids",
        "canonical_fact_ids",
        "assumption_ids",
        "calibration_artifact_ids",
        "policy_versions",
        "model_versions",
        "quality_issue_codes",
        mode="before",
    )
    @classmethod
    def normalize_identifiers(cls, value: object) -> tuple[str, ...]:
        return tuple(sorted(set(_MANIFEST_STRINGS.validate_python(value or ()))))

    @field_validator("artifact_ids", mode="before")
    @classmethod
    def preserve_artifact_order(cls, value: object) -> tuple[str, ...]:
        values = _MANIFEST_STRINGS.validate_python(value or ())
        if len(values) != len(set(values)):
            raise ValueError("artifact_ids must be unique")
        return values

    @model_validator(mode="after")
    def digest(self) -> ReleaseManifestV1:
        if self.manifest_digest != sha256_digest(
            self.model_dump(exclude={"manifest_digest"})
        ):
            raise ValueError("manifest_digest does not match release manifest")
        return self
