from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from .contracts import QualityStatus, StrictModel
from .data_releases import ArtifactRefV1
from .serialization import sha256_digest
from .statement_contracts import StatementScopeV1

FiscalFrequency = Literal["quarter", "ttm"]
FiscalStatement = Literal["income_statement", "balance_sheet", "cash_flow"]
FiscalPeriodKind = Literal["duration", "instant"]
FiscalAvailability = Literal["reported", "derived", "unavailable", "conflict"]

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FiscalDurationPeriodV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["duration"] = "duration"
    start: date
    end: date
    fiscal_year_start: date
    fiscal_year: int
    fiscal_period: Literal["Q1", "Q2", "Q3", "FY", "TTM"]
    inclusive_days: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_dates(self) -> FiscalDurationPeriodV1:
        if self.start > self.end:
            raise ValueError("fiscal duration start follows end")
        if (self.end - self.start).days + 1 != self.inclusive_days:
            raise ValueError("inclusive_days does not match duration")
        if self.fiscal_year_start > self.start:
            raise ValueError("fiscal year start follows period start")
        return self


class FiscalInstantPeriodV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["instant"] = "instant"
    instant: date
    fiscal_year: int
    fiscal_period: Literal["Q1", "Q2", "Q3", "FY", "TTM"]


FiscalPeriodV1 = Annotated[
    FiscalDurationPeriodV1 | FiscalInstantPeriodV1,
    Field(discriminator="kind"),
]


class FiscalSourceLocatorV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    primary_document_sha256: Digest
    context_id: str
    fact_index: int = Field(ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)


class FiscalReportingBasisV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    issuer_id: str
    security_id: str | None
    security_scope: str
    entity_scope: str
    currency: str
    unit: str
    consolidation_scope: str
    dimensions: tuple[tuple[str, str], ...] = ()
    cash_basis: str | None = None
    accounting_scope: str = "consolidated_us_gaap"
    revision_basis_id: str | None = None

    def same_accounting_scope(self, other: FiscalReportingBasisV1) -> bool:
        return self.model_dump(exclude={"revision_basis_id"}) == other.model_dump(
            exclude={"revision_basis_id"}
        )


class FiscalBasisObservationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    observation_digest: Digest


class FiscalBasisFilingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    accession_number: str
    primary_document_sha256: Digest
    accepted_at: AwareDatetime
    disclosure_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    amends_accession: str | None = None
    supersedes_accession: str | None = None


class FiscalComparativePairV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    original_id: str
    comparative_id: str


class FiscalRevisionBridgeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observations: tuple[FiscalBasisObservationV1, ...] = Field(min_length=2)
    disclosure_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)


class FiscalRevisionBasisProofV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-revision-basis.v1"] = (
        "fundamental.fiscal-revision-basis.v1"
    )
    row_id: str
    period: FiscalDurationPeriodV1
    observations: tuple[FiscalBasisObservationV1, ...] = Field(min_length=1)
    filings: tuple[FiscalBasisFilingV1, ...] = Field(min_length=1)
    comparative_pairs: tuple[FiscalComparativePairV1, ...] = ()
    revision_bridges: tuple[FiscalRevisionBridgeV1, ...] = ()
    intermediate_published_revisions: tuple[str, ...] = ()
    component_period_digests: tuple[Digest, ...] = ()
    source_revision: str
    cutoff_at: AwareDatetime
    public_available_at: AwareDatetime
    review_evidence_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_unique_bindings(self) -> FiscalRevisionBasisProofV1:
        observation_ids = tuple(item.observation_id for item in self.observations)
        accessions = tuple(item.accession_number for item in self.filings)
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("basis proof observation bindings must be unique")
        if len(set(accessions)) != len(accessions):
            raise ValueError("basis proof filing bindings must be unique")
        if self.public_available_at > self.cutoff_at:
            raise ValueError("basis proof sources were not available by cutoff")
        return self

    @property
    def basis_digest(self) -> str:
        return sha256_digest(self)


class ReportedQuarterV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_quarter"] = "reported_quarter"
    period: FiscalDurationPeriodV1
    applicability: Literal["quarter", "quarter_and_ytd"] = "quarter"

    @model_validator(mode="after")
    def exact_quarter_role(self) -> ReportedQuarterV1:
        if self.period.fiscal_period == "TTM":
            raise ValueError("reported quarter cannot have a TTM role")
        if (
            self.applicability == "quarter_and_ytd"
            and self.period.start != self.period.fiscal_year_start
        ):
            raise ValueError("a quarter is also YTD only at the fiscal year start")
        return self


class ReportedYtdV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_ytd"] = "reported_ytd"
    period: FiscalDurationPeriodV1

    @model_validator(mode="after")
    def exact_ytd_role(self) -> ReportedYtdV1:
        if (
            self.period.start != self.period.fiscal_year_start
            or self.period.fiscal_period not in {"Q1", "Q2", "Q3"}
        ):
            raise ValueError(
                "YTD must begin at the fiscal-year start and end before FY"
            )
        return self


class ReportedFiscalYearV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_fiscal_year"] = "reported_fiscal_year"
    period: FiscalDurationPeriodV1

    @model_validator(mode="after")
    def exact_fiscal_year_role(self) -> ReportedFiscalYearV1:
        if (
            self.period.start != self.period.fiscal_year_start
            or self.period.fiscal_period != "FY"
        ):
            raise ValueError("reported fiscal year must cover its fiscal-year start")
        return self


class ReportedInstantV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_instant"] = "reported_instant"
    instant: date


class UnsupportedDurationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unsupported_duration"] = "unsupported_duration"
    start: date
    end: date
    reason: str


FiscalReportedPeriodV1 = Annotated[
    ReportedQuarterV1
    | ReportedYtdV1
    | ReportedFiscalYearV1
    | ReportedInstantV1
    | UnsupportedDurationV1,
    Field(discriminator="kind"),
]


class OriginalFiscalRevisionV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["original"] = "original"


class AmendedFiscalRevisionV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["amendment"] = "amendment"
    scope: Literal["unknown", "comparable"]
    amends_accession: str | None = None

    @model_validator(mode="after")
    def known_scope_requires_lineage(self) -> AmendedFiscalRevisionV1:
        if self.scope == "comparable" and self.amends_accession is None:
            raise ValueError("comparable amendments require exact lineage")
        return self


FiscalFilingRevisionV1 = Annotated[
    OriginalFiscalRevisionV1 | AmendedFiscalRevisionV1, Field(discriminator="kind")
]


class FiscalObservationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    row_id: str
    statement: FiscalStatement
    source_artifact_id: str
    accession_number: str
    form: Literal["10-K", "10-Q", "10-K/A", "10-Q/A"]
    filing_revision: FiscalFilingRevisionV1 = OriginalFiscalRevisionV1()
    issuer_id: str
    accepted_at: AwareDatetime
    available_at: AwareDatetime
    filing_date: date
    report_date: date
    period: FiscalReportedPeriodV1
    basis: FiscalReportingBasisV1
    source_locator: FiscalSourceLocatorV1
    concept: str
    namespace_uri: str
    source_fact_key: str
    raw_text: str
    value: Decimal | None
    scale: int | None = None
    sign: Literal["+", "-"] | None = None
    decimals: int | Literal["INF"] | None = None
    quality: QualityStatus = QualityStatus.VERIFIED
    source_binding_digest: Digest
    parser_action_digest: Digest
    mapping_digest: Digest

    @field_validator("value", mode="before")
    @classmethod
    def decimal_boundary(cls, value: object) -> Decimal | None:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, str):
            return Decimal(value)
        raise ValueError("fiscal amounts require a Decimal or decimal string")

    @property
    def observation_digest(self) -> str:
        return sha256_digest(self)

    @model_validator(mode="after")
    def value_shape(self) -> FiscalObservationV1:
        if self.value is None and self.quality is QualityStatus.VERIFIED:
            raise ValueError("verified observation must have a value")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("fiscal observation value must be finite")
        if self.form.endswith("/A") != isinstance(
            self.filing_revision, AmendedFiscalRevisionV1
        ):
            raise ValueError("filing form and revision kind disagree")
        return self


class FiscalPeriodTargetV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    period_id: str
    period: FiscalPeriodV1
    cutoff_at: AwareDatetime
    source_binding_digest: Digest


class FiscalTtmWindowV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    window_id: str
    quarters: tuple[FiscalPeriodTargetV1, ...] = Field(min_length=4, max_length=4)
    source_binding_digest: Digest

    @model_validator(mode="after")
    def four_distinct_quarters(self) -> FiscalTtmWindowV1:
        ids = tuple(item.period_id for item in self.quarters)
        if len(set(ids)) != 4:
            raise ValueError("TTM window quarters must be distinct")
        if any(item.period.kind != "duration" for item in self.quarters):
            raise ValueError("TTM window requires duration quarters")
        return self


class FiscalInputEdgeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    input_id: str
    coefficient: Literal[-1, 1]


class FiscalCandidateDecisionV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    outcome: Literal["selected", "superseded", "equivalent_duplicate", "rejected"]
    reason: str


class FiscalPrecisionIntervalV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    lower: Decimal
    upper: Decimal
    lower_inclusive: bool = True
    upper_inclusive: bool = True

    @model_validator(mode="after")
    def ordered(self) -> FiscalPrecisionIntervalV1:
        if (
            not self.lower.is_finite()
            or not self.upper.is_finite()
            or self.lower > self.upper
        ):
            raise ValueError("precision interval is inverted")
        return self

    def overlaps(self, other: FiscalPrecisionIntervalV1) -> bool:
        left = self.lower < other.upper or (
            self.lower == other.upper and self.lower_inclusive and other.upper_inclusive
        )
        right = other.lower < self.upper or (
            other.lower == self.upper and other.lower_inclusive and self.upper_inclusive
        )
        return left and right


class FiscalValueNodeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    row_id: str
    statement: FiscalStatement
    frequency: FiscalFrequency
    period: FiscalPeriodV1
    availability: FiscalAvailability
    value: Decimal | None
    source_observation_ids: tuple[str, ...] = ()
    verification_observation_ids: tuple[str, ...] = ()
    verification_node_ids: tuple[str, ...] = ()
    formula: str | None = None
    policy_id: str
    executable_digest: Digest
    input_edges: tuple[FiscalInputEdgeV1, ...] = ()
    verification_edges: tuple[FiscalInputEdgeV1, ...] = ()
    source_binding_digest: Digest
    reporting_basis: FiscalReportingBasisV1 | None = None
    revision_basis_proof: FiscalRevisionBasisProofV1 | None = None
    quality: QualityStatus
    available_at: AwareDatetime | None = None
    precision_interval: FiscalPrecisionIntervalV1 | None = None
    reason_code: str | None = None
    candidates: tuple[FiscalCandidateDecisionV1, ...] = ()

    @model_validator(mode="after")
    def value_matches_status(self) -> FiscalValueNodeV1:
        if self.availability in {"unavailable", "conflict"} and self.value is not None:
            raise ValueError("unavailable or conflicting nodes cannot have a value")
        if self.availability in {"reported", "derived"} and self.value is None:
            raise ValueError("available nodes require a value")
        if self.availability == "derived" and (
            self.formula is None or not self.input_edges
        ):
            raise ValueError("derived nodes require a versioned formula and inputs")
        return self


class FiscalReconciliationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    period_id: str
    frequency: FiscalFrequency
    rule: Literal["opening_plus_change_equals_closing", "flows_plus_fx_equals_change"]
    status: Literal[
        "consistent_at_reported_precision",
        "conflict",
        "unresolved_missing_inputs",
        "unresolved_precision",
    ]
    input_node_ids: tuple[str, ...]
    residual: Decimal | None
    precision_interval: FiscalPrecisionIntervalV1 | None
    reason_code: str | None = None


class FiscalCashContinuityV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    window_id: str
    boundary_date: date
    status: Literal[
        "consistent_at_reported_precision",
        "conflict",
        "unresolved_missing_inputs",
        "unresolved_precision",
    ]
    input_node_ids: tuple[str, ...]
    reason_code: str | None = None


class FiscalProjectionInputV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observations: tuple[FiscalObservationV1, ...] = Field(min_length=1)
    scope: StatementScopeV1
    quarter_targets: tuple[FiscalPeriodTargetV1, ...] = ()
    ttm_windows: tuple[FiscalTtmWindowV1, ...] = ()
    cutoff_at: AwareDatetime
    source_binding_digest: Digest
    basis_proofs: tuple[FiscalRevisionBasisProofV1, ...] = ()
    source_revision: str
    executable_digest: Digest


class FiscalProjectionResultV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    executable_digest: Digest
    quarter_nodes: tuple[FiscalValueNodeV1, ...]
    ttm_nodes: tuple[FiscalValueNodeV1, ...]
    unsupported_rows: tuple[str, ...] = ()
    source_observations: tuple[FiscalObservationV1, ...] = ()
    reconciliations: tuple[FiscalReconciliationV1, ...] = ()
    cash_continuities: tuple[FiscalCashContinuityV1, ...] = ()
    quarter_periods: tuple[FiscalPeriodTargetV1, ...] = ()
    ttm_windows: tuple[FiscalTtmWindowV1, ...] = ()
    quality: QualityStatus = QualityStatus.PROVISIONAL
    supported_history_threshold: None = None
    valuation_eligibility: Literal["not_evaluated"] = "not_evaluated"

    @property
    def nodes(self) -> tuple[FiscalValueNodeV1, ...]:
        return self.quarter_nodes + self.ttm_nodes
