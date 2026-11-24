from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from .fundamental_contracts import (
    CanonicalDecimal,
    FundamentalCandidateRejectionV1,
    FundamentalCanonicalFactV1,
    FundamentalMissingValueV1,
    FundamentalQualityStatus,
)


def _canonical_statement_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical_statement_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical_statement_value(item) for item in value]
    return value


class StatementTransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StatementArtifactRefV1(StatementTransportModel):
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1)
    role: str = Field(min_length=1)


class StatementMappingV1(StatementTransportModel):
    contract_version: Literal["fundamental.v1"]
    decision_id: str
    source_concept: str
    normalized_field: str
    mapping_version: str
    anchor_concept: str | None = None
    confidence: Literal["high", "medium", "low", "unresolved"]
    evidence_refs: tuple[str, ...] = ()
    reviewer: str | None = None
    reviewed_at: AwareDatetime | None = None
    status: Literal["approved", "provisional", "ambiguous", "rejected"]
    accounting_rules: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    observation_scope: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class StatementSourceRecordV1(StatementTransportModel):
    source_id: str
    uri: str
    role: Literal[
        "filing",
        "company_facts",
        "taxonomy",
        "acquisition",
        "macro",
        "market",
        "reference",
    ]
    available_at: AwareDatetime
    captured_at: AwareDatetime
    publication_at: AwareDatetime | None = None
    http_status: int = Field(ge=100, le=599)
    media_type: str
    terms_reference: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str | None = None
    parser_version: str
    accession_number: str | None = None
    form: str | None = None
    filing_date: date | None = None
    filed_at: AwareDatetime | None = None
    filing_version: str | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    taxonomy_manifest_id: str | None = None
    response_headers: tuple[tuple[str, str], ...] = ()
    declared_size: int | None = None
    received_size: int | None = None
    point_in_time_relevant: bool = True


StatementSeverity = Literal["info", "warning", "error", "fatal"]

Digest = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]

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


class StatementScopeV1(StatementTransportModel):
    issuer_id: str = Field(min_length=1)
    security_id: str | None
    security_scope: str
    entity_scope: str
    currency: str
    unit: str
    consolidation_scope: Literal["consolidated"] = "consolidated"


class DurationStatementPeriodV1(StatementTransportModel):
    kind: Literal["duration"] = "duration"
    period_start: date
    period_end: date


class InstantStatementPeriodV1(StatementTransportModel):
    kind: Literal["instant"] = "instant"
    instant: date


class UnresolvedStatementPeriodV1(StatementTransportModel):
    kind: Literal["unresolved"] = "unresolved"
    reported_period_end: date
    missing: FundamentalMissingValueV1
    source_outcome_ref: StatementArtifactRefV1


StatementPeriodV1 = Annotated[
    DurationStatementPeriodV1 | InstantStatementPeriodV1 | UnresolvedStatementPeriodV1,
    Field(discriminator="kind"),
]


class StatementColumnV1(StatementTransportModel):
    period_id: Digest
    fiscal_label: str
    period: StatementPeriodV1
    duration_days: int | None
    calendar: Literal["52_week", "53_week", "calendar_year", "other", "unresolved"]


class StatementRowDefinitionV1(StatementTransportModel):
    row_id: StatementRowId
    statement: StatementKind
    label: str
    value_period_role: ValuePeriodRole
    concepts: tuple[str, ...] = Field(min_length=1)
    sign_policy: Literal["reported_signed_decimal_v1"] = "reported_signed_decimal_v1"


class StatementProfileV1(StatementTransportModel):
    profile_id: Literal["us-gaap-nonfinancial-annual-v1"]
    contract_version: Literal["fundamental.annual-statements.v1"]
    rows: tuple[StatementRowDefinitionV1, ...]
    selection_policy: Literal["canonical-pit-exact-row-key-v1"]
    reconciliation_policy: Literal["reported-decimals-half-unit-sum-v1"]
    comparability_policy: Literal["actual-annual-periods-no-annualization-v1"]
    executable_digest: Digest
    history_coverage_target: Literal[5] = 5
    supported_history_threshold: None = None


class StatementFactEvidenceV1(StatementTransportModel):
    fact: FundamentalCanonicalFactV1
    mapping: StatementMappingV1
    source: StatementSourceRecordV1
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: Digest
    mapping_evidence_refs: tuple[StatementArtifactRefV1, ...] = ()
    cash_basis: CashBasis | None = None


class StatementAvailableSourceV1(StatementTransportModel):
    kind: Literal["available"] = "available"
    accession_number: str
    available_at: AwareDatetime
    report_period_end: date
    outcome_ref: StatementArtifactRefV1
    fact_ids: tuple[str, ...]


class StatementUnavailableSourceV1(StatementTransportModel):
    kind: Literal["unavailable"] = "unavailable"
    accession_number: str
    available_at: AwareDatetime
    report_period_end: date
    outcome_ref: StatementArtifactRefV1
    quality_status: FundamentalQualityStatus
    missing: FundamentalMissingValueV1
    issue_codes: tuple[str, ...] = Field(min_length=1)


StatementSourceOutcomeV1 = Annotated[
    StatementAvailableSourceV1 | StatementUnavailableSourceV1,
    Field(discriminator="kind"),
]


class StatementNumericFactV1(FundamentalCanonicalFactV1):
    value: CanonicalDecimal


class ReportedStatementCellV1(StatementTransportModel):
    status: Literal["reported"] = "reported"
    cell_id: Digest
    row_id: StatementRowId
    period_id: Digest
    selected_version_id: Digest
    fact: StatementNumericFactV1
    snapshot_id: str
    snapshot_manifest_digest: Digest
    mapping_digest: Digest
    mapping_evidence_refs: tuple[StatementArtifactRefV1, ...]
    cash_basis: CashBasis | None
    selection_reason: str
    selection_kind: Literal["original", "amended", "later_comparative"]
    source_report_period_end: date
    candidate_fact_ids: tuple[str, ...]
    rejected_candidates: tuple[FundamentalCandidateRejectionV1, ...]
    quality_status: FundamentalQualityStatus = "verified"


class UnavailableStatementCellV1(StatementTransportModel):
    status: Literal["unavailable"] = "unavailable"
    cell_id: Digest
    row_id: StatementRowId
    period_id: Digest
    missing: FundamentalMissingValueV1
    quality_status: FundamentalQualityStatus
    issue_codes: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[StatementArtifactRefV1, ...]
    candidate_fact_ids: tuple[str, ...] = ()
    rejected_candidates: tuple[FundamentalCandidateRejectionV1, ...] = ()


StatementCellV1 = Annotated[
    ReportedStatementCellV1 | UnavailableStatementCellV1, Field(discriminator="status")
]


class StatementRowV1(StatementTransportModel):
    definition: StatementRowDefinitionV1
    cells: tuple[StatementCellV1, ...]


class StatementTableV1(StatementTransportModel):
    statement: StatementKind
    columns: tuple[StatementColumnV1, ...]
    rows: tuple[StatementRowV1, ...]


class StatementComparabilityV1(StatementTransportModel):
    earlier_period_id: Digest
    later_period_id: Digest
    status: Literal["comparable", "limited", "not_comparable"]
    issue_codes: tuple[str, ...]
    affected_row_ids: tuple[StatementRowId, ...] = ()


class StatementReconciliationV1(StatementTransportModel):
    statement: StatementKind
    period_id: Digest
    check_id: str
    status: Literal["passed", "rounding", "unresolved", "not_applicable", "failed"]
    severity: StatementSeverity
    expression: str
    input_fact_ids: tuple[str, ...]
    difference: CanonicalDecimal | None
    tolerance: CanonicalDecimal | None
    issue_codes: tuple[str, ...]
    policy_version: Literal["reported-decimals-half-unit-sum-v1"]


class StatementCoverageV1(StatementTransportModel):
    period_id: Digest
    statement: StatementKind
    fiscal_label: str
    reported_rows: int
    declared_rows: int
    unavailable_row_ids: tuple[StatementRowId, ...]


class AnnualStatementsV1(StatementTransportModel):
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
    quality_status: FundamentalQualityStatus
    valuation_eligibility: Literal["not_evaluated"] = "not_evaluated"


class AnnualStatementsReadRequestV1(StatementTransportModel):
    contract_version: Literal["fundamental.annual-statements.v1"] = (
        "fundamental.annual-statements.v1"
    )
    data_release_manifest_digest: Digest
    cutoff_at: AwareDatetime


class AnnualStatementsReadResponseV1(StatementTransportModel):
    contract_version: Literal["fundamental.annual-statements.v1"]
    data_release_manifest_digest: Digest
    statements: AnnualStatementsV1

    @model_validator(mode="after")
    def validate_transport_binding(self) -> AnnualStatementsReadResponseV1:
        statement = self.statements
        canonical = json.dumps(
            _canonical_statement_value(
                statement.model_dump(mode="python", exclude={"statement_id"})
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != statement.statement_id:
            raise ValueError("STATEMENT_RESULT_DIGEST_MISMATCH")
        all_periods: set[str] = set()
        cell_ids: set[str] = set()
        candidate_ids = {item.fact.fact_id for item in statement.candidate_evidence}
        for table in statement.tables:
            periods = tuple(column.period_id for column in table.columns)
            if len(set(periods)) != len(periods):
                raise ValueError("STATEMENT_PERIOD_DUPLICATE")
            all_periods.update(periods)
            for row in table.rows:
                if (
                    row.definition.statement != table.statement
                    or tuple(cell.period_id for cell in row.cells) != periods
                ):
                    raise ValueError("STATEMENT_ROW_PERIOD_MISMATCH")
                for cell in row.cells:
                    if cell.row_id != row.definition.row_id or cell.cell_id in cell_ids:
                        raise ValueError("STATEMENT_CELL_IDENTITY_MISMATCH")
                    cell_ids.add(cell.cell_id)
                    if isinstance(cell, ReportedStatementCellV1):
                        fact = cell.fact
                        if not isinstance(fact.value, str):
                            raise ValueError("STATEMENT_VALUE_NOT_DECIMAL")
                        try:
                            value = Decimal(fact.value)
                        except InvalidOperation as error:
                            raise ValueError("STATEMENT_VALUE_NOT_DECIMAL") from error
                        if not value.is_finite():
                            raise ValueError("STATEMENT_VALUE_NOT_DECIMAL")
                        if (
                            fact.issuer_id != statement.scope.issuer_id
                            or fact.normalized_field != cell.row_id
                            or fact.available_at > statement.cutoff_at
                        ):
                            raise ValueError("STATEMENT_FACT_SCOPE_MISMATCH")
                        if (
                            fact.fact_id not in candidate_ids
                            or fact.fact_id not in cell.candidate_fact_ids
                        ):
                            raise ValueError("STATEMENT_SELECTED_EVIDENCE_MISSING")
                        if (
                            not fact.context.context_id
                            or fact.context.concept_qname != fact.concept
                            or fact.source.content_hash == ""
                            or fact.source.accession_number != fact.accession_number
                        ):
                            raise ValueError("STATEMENT_FACT_EVIDENCE_MISMATCH")
        if len({table.statement for table in statement.tables}) != len(
            statement.tables
        ):
            raise ValueError("STATEMENT_TABLE_DUPLICATE")
        if any(
            item.period_id not in all_periods
            for item in (*statement.coverage, *statement.reconciliations)
        ):
            raise ValueError("STATEMENT_PERIOD_REFERENCE_MISMATCH")
        return self
