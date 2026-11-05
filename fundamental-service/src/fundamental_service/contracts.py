"""Strict public and internal contracts for the first Fundamental service slice."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .serialization import is_digest, sha256_digest

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
    def timestamps_have_timezone(self) -> "SourceProvenanceV1":
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
    expression: str | None = None
    inputs: tuple[str, ...] = ()
    description: str | None = None

    @model_validator(mode="after")
    def require_trace(self) -> "TraceV1":
        if not self.source_refs and not self.expression and not self.description:
            raise ValueError("a trace requires source_refs, expression, or description")
        return self


class IdentityV1(StrictModel):
    issuer_id: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    domicile: str = Field(min_length=2, max_length=2)
    reporting_basis: Literal["us-gaap", "ifrs"]
    security_id: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


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
    def period_shape(self) -> "XbrlContextV1":
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
    parser_version: str = Field(min_length=1)
    accession_number: str | None = None
    form: str | None = None
    filed_at: datetime | None = None
    filing_version: str | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    taxonomy_manifest_id: str | None = None

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> "SourceRecordV1":
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


class SourceSnapshotV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    identity: IdentityV1
    valuation_timestamp: datetime
    captured_at: datetime
    source_records: tuple[SourceRecordV1, ...] = Field(min_length=1)
    taxonomy_manifest_id: str | None = None
    parser_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    coverage_status: QualityStatus
    issues: tuple[IssueV1, ...] = ()
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> "SourceSnapshotV1":
        payload = self.model_dump(exclude={"manifest_digest", "snapshot_id"})
        if self.manifest_digest != sha256_digest(payload):
            raise ValueError(
                "manifest_digest does not match canonical snapshot manifest"
            )
        return self

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> "SourceSnapshotV1":
        for name, value in (
            ("valuation_timestamp", self.valuation_timestamp),
            ("captured_at", self.captured_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        return self


class SnapshotResolutionRequestV1(StrictModel):
    """Caller-owned point-in-time selector for an immutable data snapshot."""

    contract_version: Literal["fundamental.v1"]
    identity: IdentityV1
    valuation_timestamp: datetime
    source_selection_policy: Literal["pit-v1"]
    coverage_profile: str = Field(min_length=1)
    required_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation_timestamp must include a timezone")
        return value


class SnapshotResolutionV1(StrictModel):
    """Immutable references needed to construct a complete valuation input."""

    contract_version: Literal["fundamental.v1"]
    snapshot_id: str = Field(min_length=1)
    historical_facts: tuple[str, ...] = Field(min_length=1)
    identity: IdentityV1
    valuation_timestamp: datetime
    source_selection_policy: str = Field(min_length=1)
    coverage_profile: str = Field(min_length=1)
    quality: QualityStatus
    issue_codes: tuple[str, ...] = ()
    provenance: dict[str, str | None]


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

    @model_validator(mode="after")
    def point_in_time_order(self) -> "CanonicalFactV1":
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
    def timestamps_have_timezone(self) -> "CanonicalFactV1":
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
    def weights_and_rates(self) -> "WaccAssumptionsV1":
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
    def cet1_ratio(self) -> Decimal:
        return self.cet1_capital / self.reported_rwa

    @model_validator(mode="after")
    def regulatory_constraints(self) -> "BankAssumptionsV1":
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


class DistributionParameterV1(StrictModel):
    path: str = Field(min_length=1)
    distribution: Literal["normal", "lognormal", "uniform", "triangular"]
    lower: Decimal
    upper: Decimal
    mode: Decimal | None = None
    mean: Decimal | None = None

    @model_validator(mode="after")
    def bounds(self) -> "DistributionParameterV1":
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
    correlations: tuple[tuple[str, str, Decimal], ...] = ()
    invalid_draw_policy: Literal["reject", "skip", "abstain"] | None = None
    scenarios: tuple[ScenarioInputV1, ...] = ()
    sensitivity: tuple[SensitivityInputV1, ...] = ()

    @model_validator(mode="after")
    def sampling_requirements(self) -> "UncertaintyV1":
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
            or self.correlations
            or self.invalid_draw_policy is not None
        ):
            raise ValueError("mode none cannot include sampling controls")
        return self


class QualityInputV1(StrictModel):
    status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class ValuationContextV1(StrictModel):
    valuation_timestamp: datetime
    data_snapshot_id: str = Field(min_length=1)
    source_selection_policy: str = Field(min_length=1)
    coverage_profile: str = Field(min_length=1)


class ProvenanceInputV1(StrictModel):
    snapshot_id: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = ()
    mapping_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    policy_version: str | None = None


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
    def model_assumptions_present(self) -> "ValuationInputV1":
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
    def digest_and_approval(self) -> "ValuationInputV1":
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

    def with_digest(self) -> "ValuationInputV1":
        digest = sha256_digest(
            self.model_dump(exclude={"input_digest", "caller_approval"})
        )
        return self.model_copy(update={"input_digest": digest})


class ValidationResponseV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    input: ValuationInputV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: QualityStatus
    policy_resolution: "PolicyResolutionV1"
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class PolicyResolutionV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    source_selection_policy: str = Field(min_length=1)
    source_selection_policy_version: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_ids: tuple[str, ...] = Field(min_length=1)
    source_content_hashes: tuple[str, ...] = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    assumptions_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_version: str = Field(min_length=1)


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
    evaluated_at: datetime
    correlation_id: str = Field(min_length=1)


class CalculationEvidenceV1(StrictModel):
    contract_version: Literal["fundamental.v1"]
    request: ValuationInputV1
    calculation: CalculationArtifactV1

    @model_validator(mode="after")
    def evidence_is_digest_bound(self) -> "CalculationEvidenceV1":
        calculation = self.calculation
        trace = calculation.trace
        if trace is None:
            raise ValueError("calculation evidence requires a complete trace")
        if self.request.caller_approval is not None:
            raise ValueError("caller approval evidence must not be persisted")
        if (
            calculation.input_digest != self.request.input_digest
            or calculation.snapshot_id != trace.snapshot_id
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
        values = tuple(value or ())
        if any(not is_digest(item) for item in values):
            raise ValueError("manifest hash fields must contain SHA-256 digests")
        return tuple(sorted(set(values)))

    @field_validator("artifact_hashes", mode="before")
    @classmethod
    def preserve_artifact_hash_order(cls, value: object) -> tuple[str, ...]:
        values = tuple(value or ())
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
        return tuple(sorted(set(value or ())))

    @field_validator("artifact_ids", mode="before")
    @classmethod
    def preserve_artifact_order(cls, value: object) -> tuple[str, ...]:
        values = tuple(value or ())
        if len(values) != len(set(values)):
            raise ValueError("artifact_ids must be unique")
        return values

    @model_validator(mode="after")
    def digest(self) -> "ReleaseManifestV1":
        if self.manifest_digest != sha256_digest(
            self.model_dump(exclude={"manifest_digest"})
        ):
            raise ValueError("manifest_digest does not match release manifest")
        return self
