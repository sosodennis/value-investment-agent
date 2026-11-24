"""Versioned annual statement periods, cell evidence, and coverage outcomes."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .contracts import (
    CandidateRejectionV1,
    CanonicalFactV1,
    MissingValueV1,
    QualityStatus,
    Severity,
    SourceRecordV1,
    SourceRole,
)
from .data_releases import ArtifactRefV1, ReleaseModel
from .facts import CanonicalMappingV1
from .serialization import sha256_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
StatementKind = Literal["income_statement", "balance_sheet", "cash_flow"]
StatementRowId = Literal[
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
    "net_income",
    "cash_and_equivalents",
    "operating_current_receivables",
    "inventory",
    "current_assets",
    "property_plant_and_equipment",
    "total_assets",
    "operating_current_payables",
    "current_liabilities",
    "total_liabilities",
    "total_equity",
    "liabilities_and_equity",
    "operating_cash_flow",
    "investing_cash_flow",
    "financing_cash_flow",
    "effect_of_exchange_rates_on_cash",
    "net_change_in_cash",
    "cash_flow_beginning_balance",
    "cash_flow_ending_balance",
]
ValuePeriodRole = Literal["duration", "period_end", "day_before_period_start"]
CashBasis = Literal["cash_and_equivalents", "cash_equivalents_and_restricted_cash"]


class StatementScopeV1(ReleaseModel):
    issuer_id: str = Field(min_length=1)
    security_id: str | None
    security_scope: str
    entity_scope: str
    currency: str
    unit: str
    consolidation_scope: Literal["consolidated"] = "consolidated"


class DurationStatementPeriodV1(ReleaseModel):
    kind: Literal["duration"] = "duration"
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> DurationStatementPeriodV1:
        if self.period_start > self.period_end:
            raise ValueError("statement duration start follows its end")
        return self

    @property
    def duration_days(self) -> int:
        return (self.period_end - self.period_start).days + 1


class InstantStatementPeriodV1(ReleaseModel):
    kind: Literal["instant"] = "instant"
    instant: date


class UnresolvedStatementPeriodV1(ReleaseModel):
    kind: Literal["unresolved"] = "unresolved"
    reported_period_end: date
    missing: MissingValueV1
    source_outcome_ref: ArtifactRefV1


StatementPeriodV1 = Annotated[
    DurationStatementPeriodV1 | InstantStatementPeriodV1 | UnresolvedStatementPeriodV1,
    Field(discriminator="kind"),
]
AnnualStatementPeriodV1 = Annotated[
    DurationStatementPeriodV1 | UnresolvedStatementPeriodV1,
    Field(discriminator="kind"),
]


def statement_period_id(scope: StatementScopeV1, period: StatementPeriodV1) -> str:
    return sha256_digest({"scope": scope, "period": period})


class StatementAnnualColumnV1(ReleaseModel):
    fiscal_label: str = Field(min_length=1)
    period: AnnualStatementPeriodV1
    original_accession: str = Field(min_length=1)

    @property
    def period_end(self) -> date:
        if isinstance(self.period, DurationStatementPeriodV1):
            return self.period.period_end
        return self.period.reported_period_end


class StatementColumnV1(ReleaseModel):
    period_id: Digest
    fiscal_label: str
    period: StatementPeriodV1
    duration_days: int | None
    calendar: Literal["52_week", "53_week", "calendar_year", "other", "unresolved"]


class StatementRowDefinitionV1(ReleaseModel):
    row_id: StatementRowId
    statement: StatementKind
    label: str
    value_period_role: ValuePeriodRole
    concepts: tuple[str, ...] = Field(min_length=1)
    sign_policy: Literal["reported_signed_decimal_v1"] = "reported_signed_decimal_v1"


class StatementProfileV1(ReleaseModel):
    profile_id: Literal["us-gaap-nonfinancial-annual-v1"]
    contract_version: Literal["fundamental.annual-statements.v1"]
    rows: tuple[StatementRowDefinitionV1, ...]
    selection_policy: Literal["canonical-pit-exact-row-key-v1"]
    reconciliation_policy: Literal["reported-decimals-half-unit-sum-v1"]
    comparability_policy: Literal["actual-annual-periods-no-annualization-v1"]
    executable_digest: Digest
    history_coverage_target: Literal[5] = 5
    supported_history_threshold: None = None

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class StatementFactEvidenceV1(ReleaseModel):
    fact: CanonicalFactV1
    mapping: CanonicalMappingV1
    source: SourceRecordV1
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: Digest
    mapping_evidence_refs: tuple[ArtifactRefV1, ...] = ()
    cash_basis: CashBasis | None = None

    @model_validator(mode="after")
    def fact_is_bound_to_source_and_mapping(self) -> StatementFactEvidenceV1:
        fact, source, mapping = self.fact, self.source, self.mapping
        if (
            fact.source.content_hash != source.content_hash
            or fact.source.source_url != source.uri
            or fact.accession_number != source.accession_number
            or fact.source.accession_number != fact.accession_number
            or source.role is not SourceRole.FILING
            or fact.source.source_role is not SourceRole.FILING
            or fact.mapping_decision_id != mapping.decision_id
            or fact.normalized_field != mapping.normalized_field
            or fact.concept != mapping.source_concept
            or fact.context.concept_qname != fact.concept
            or fact.context.start_date != fact.period_start
            or fact.context.instant != fact.instant
            or fact.context.end_date
            != (None if fact.instant is not None else fact.period_end)
        ):
            raise ValueError("STATEMENT_FACT_EVIDENCE_MISMATCH")
        if fact.quality is not QualityStatus.VERIFIED or mapping.status != "approved":
            raise ValueError("STATEMENT_FACT_NOT_VERIFIED")
        if not isinstance(fact.value, Decimal) or not fact.value.is_finite():
            raise ValueError("STATEMENT_FACT_NOT_FINITE_DECIMAL")
        return self


class StatementAvailableSourceV1(ReleaseModel):
    kind: Literal["available"] = "available"
    accession_number: str
    available_at: AwareDatetime
    report_period_end: date
    outcome_ref: ArtifactRefV1
    fact_ids: tuple[str, ...]

    @model_validator(mode="after")
    def declared_facts_are_unique(self) -> StatementAvailableSourceV1:
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("STATEMENT_DECLARED_FACT_DUPLICATE")
        if self.report_period_end > self.available_at.date():
            raise ValueError("STATEMENT_ORIGINAL_PERIOD_AFTER_PUBLICATION")
        return self


class StatementUnavailableSourceV1(ReleaseModel):
    kind: Literal["unavailable"] = "unavailable"
    accession_number: str
    available_at: AwareDatetime
    report_period_end: date
    outcome_ref: ArtifactRefV1
    quality_status: QualityStatus
    missing: MissingValueV1
    issue_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unavailable_is_not_verified(self) -> StatementUnavailableSourceV1:
        if self.quality_status is QualityStatus.VERIFIED:
            raise ValueError("an unavailable original cannot be verified")
        if self.report_period_end > self.available_at.date():
            raise ValueError("STATEMENT_ORIGINAL_PERIOD_AFTER_PUBLICATION")
        return self


StatementSourceOutcomeV1 = Annotated[
    StatementAvailableSourceV1 | StatementUnavailableSourceV1,
    Field(discriminator="kind"),
]


class StatementMissingEvidenceV1(ReleaseModel):
    row_id: StatementRowId
    period_id: Digest
    missing: MissingValueV1
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)


class StatementProjectionInputV1(ReleaseModel):
    protocol: Literal["annual-statement-projection-input-v1"] = (
        "annual-statement-projection-input-v1"
    )
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    coverage_cutoff_at: AwareDatetime
    profile: StatementProfileV1
    discovery_ref: ArtifactRefV1
    columns: tuple[StatementAnnualColumnV1, ...] = Field(min_length=1)
    source_outcomes: tuple[StatementSourceOutcomeV1, ...] = Field(min_length=1)
    facts: tuple[StatementFactEvidenceV1, ...]
    missing_evidence: tuple[StatementMissingEvidenceV1, ...] = ()

    @model_validator(mode="after")
    def coverage_and_sources_are_exact(self) -> StatementProjectionInputV1:
        if self.cutoff_at != self.coverage_cutoff_at:
            raise ValueError("STATEMENT_CUTOFF_OUTSIDE_COVERAGE")
        sources = {source.accession_number: source for source in self.source_outcomes}
        if len(sources) != len(self.source_outcomes):
            raise ValueError("STATEMENT_ORIGINAL_OUTCOME_DUPLICATE")
        periods = [
            statement_period_id(self.scope, column.period) for column in self.columns
        ]
        if len(set(periods)) != len(periods):
            raise ValueError("STATEMENT_PERIOD_DUPLICATE")
        if len({item.fact.fact_id for item in self.facts}) != len(self.facts):
            raise ValueError("STATEMENT_FACT_DUPLICATE")
        declared = {
            fact_id
            for source in self.source_outcomes
            if isinstance(source, StatementAvailableSourceV1)
            for fact_id in source.fact_ids
        }
        if declared != {item.fact.fact_id for item in self.facts}:
            raise ValueError("STATEMENT_DECLARED_FACT_UNAVAILABLE")
        for column in self.columns:
            source = sources.get(column.original_accession)
            if source is None or source.report_period_end != column.period_end:
                raise ValueError("STATEMENT_COLUMN_SOURCE_MISMATCH")
            if source.available_at > self.cutoff_at:
                raise ValueError("STATEMENT_COLUMN_NOT_AVAILABLE_AT_CUTOFF")
            if (
                isinstance(column.period, UnresolvedStatementPeriodV1)
                and column.period.source_outcome_ref != source.outcome_ref
            ):
                raise ValueError("STATEMENT_UNRESOLVED_PERIOD_SOURCE_MISMATCH")
        for evidence in self.facts:
            fact = evidence.fact
            source = sources.get(fact.accession_number or "")
            if (
                fact.issuer_id != self.scope.issuer_id
                or source is None
                or not isinstance(source, StatementAvailableSourceV1)
                or fact.fact_id not in source.fact_ids
            ):
                raise ValueError("STATEMENT_FACT_SOURCE_SCOPE_MISMATCH")
        missing_keys = [(item.row_id, item.period_id) for item in self.missing_evidence]
        if len(set(missing_keys)) != len(missing_keys):
            raise ValueError("STATEMENT_MISSING_EVIDENCE_DUPLICATE")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(
            {
                **self.model_dump(
                    exclude={"facts", "source_outcomes", "columns", "missing_evidence"}
                ),
                "facts": sorted(self.facts, key=lambda item: item.fact.fact_id),
                "source_outcomes": sorted(
                    self.source_outcomes, key=lambda item: item.accession_number
                ),
                "columns": sorted(
                    self.columns, key=lambda item: (item.period_end, item.fiscal_label)
                ),
                "missing_evidence": sorted(
                    self.missing_evidence,
                    key=lambda item: (item.period_id, item.row_id),
                ),
            }
        )


class ReportedStatementCellV1(ReleaseModel):
    status: Literal["reported"] = "reported"
    cell_id: Digest
    row_id: StatementRowId
    period_id: Digest
    selected_version_id: Digest
    fact: CanonicalFactV1
    snapshot_id: str
    snapshot_manifest_digest: Digest
    mapping_digest: Digest
    mapping_evidence_refs: tuple[ArtifactRefV1, ...]
    cash_basis: CashBasis | None
    selection_reason: str
    selection_kind: Literal["original", "amended", "later_comparative"]
    source_report_period_end: date
    candidate_fact_ids: tuple[str, ...]
    rejected_candidates: tuple[CandidateRejectionV1, ...]
    quality_status: QualityStatus = QualityStatus.VERIFIED

    @model_validator(mode="after")
    def reported_value_is_numeric(self) -> ReportedStatementCellV1:
        if not isinstance(self.fact.value, Decimal) or not self.fact.value.is_finite():
            raise ValueError("reported statement cells require a finite Decimal fact")
        if self.fact.normalized_field != self.row_id:
            raise ValueError("statement row differs from its selected fact")
        return self


class UnavailableStatementCellV1(ReleaseModel):
    status: Literal["unavailable"] = "unavailable"
    cell_id: Digest
    row_id: StatementRowId
    period_id: Digest
    missing: MissingValueV1
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[ArtifactRefV1, ...]
    candidate_fact_ids: tuple[str, ...] = ()
    rejected_candidates: tuple[CandidateRejectionV1, ...] = ()


StatementCellV1 = Annotated[
    ReportedStatementCellV1 | UnavailableStatementCellV1,
    Field(discriminator="status"),
]


class StatementRowV1(ReleaseModel):
    definition: StatementRowDefinitionV1
    cells: tuple[StatementCellV1, ...]


class StatementTableV1(ReleaseModel):
    statement: StatementKind
    columns: tuple[StatementColumnV1, ...]
    rows: tuple[StatementRowV1, ...]

    @model_validator(mode="after")
    def rows_align_to_columns(self) -> StatementTableV1:
        periods = tuple(column.period_id for column in self.columns)
        for row in self.rows:
            if (
                row.definition.statement != self.statement
                or tuple(cell.period_id for cell in row.cells) != periods
            ):
                raise ValueError(
                    "statement row must match its table and ordered columns"
                )
            if any(cell.row_id != row.definition.row_id for cell in row.cells):
                raise ValueError("statement cell belongs to another row")
        return self


class StatementComparabilityV1(ReleaseModel):
    earlier_period_id: Digest
    later_period_id: Digest
    status: Literal["comparable", "limited", "not_comparable"]
    issue_codes: tuple[str, ...]
    affected_row_ids: tuple[StatementRowId, ...] = ()


class StatementReconciliationV1(ReleaseModel):
    statement: StatementKind
    period_id: Digest
    check_id: str
    status: Literal["passed", "rounding", "unresolved", "not_applicable", "failed"]
    severity: Severity
    expression: str
    input_fact_ids: tuple[str, ...]
    difference: Decimal | None
    tolerance: Decimal | None
    issue_codes: tuple[str, ...]
    policy_version: Literal["reported-decimals-half-unit-sum-v1"]


class StatementCoverageV1(ReleaseModel):
    period_id: Digest
    statement: StatementKind
    fiscal_label: str
    reported_rows: int
    declared_rows: int
    unavailable_row_ids: tuple[StatementRowId, ...]


class AnnualStatementsV1(ReleaseModel):
    contract_version: Literal["fundamental.annual-statements.v1"]
    statement_id: Digest
    input_digest: Digest
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    profile: StatementProfileV1
    tables: tuple[StatementTableV1, ...]
    source_outcomes: tuple[StatementSourceOutcomeV1, ...]
    candidate_evidence: tuple[StatementFactEvidenceV1, ...]
    coverage: tuple[StatementCoverageV1, ...]
    comparability: tuple[StatementComparabilityV1, ...]
    reconciliations: tuple[StatementReconciliationV1, ...]
    quality_status: QualityStatus
    valuation_eligibility: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def result_digest_matches(self) -> AnnualStatementsV1:
        if (
            sha256_digest(self.model_dump(exclude={"statement_id"}))
            != self.statement_id
        ):
            raise ValueError("STATEMENT_RESULT_DIGEST_MISMATCH")
        return self


def value_period(
    column: StatementColumnV1,
    role: ValuePeriodRole,
) -> DurationStatementPeriodV1 | InstantStatementPeriodV1 | None:
    period = column.period
    if isinstance(period, UnresolvedStatementPeriodV1):
        return None
    if role == "duration":
        return period if isinstance(period, DurationStatementPeriodV1) else None
    if isinstance(period, InstantStatementPeriodV1):
        return period if role == "period_end" else None
    return InstantStatementPeriodV1(
        instant=period.period_end
        if role == "period_end"
        else period.period_start - timedelta(days=1)
    )
