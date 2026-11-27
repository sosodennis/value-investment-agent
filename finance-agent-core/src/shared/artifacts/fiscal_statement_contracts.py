"""Generated consumer of the Fundamental fiscal-statements.v2 wire.

Regenerate with scripts/generate-fiscal-wire-contract.py; service declarations
own the shape. Consumer-only Decimal string validation is added at decoding.

Field shapes and wire validators follow the service-owned DTO. No projection,
selection, financial calculation, or admission policy is implemented here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from src.shared.artifacts.annual_statement_contracts import (
    StatementRowId,
    StatementScopeV1,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FiscalTransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _wire_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str | Decimal):
        raise ValueError("fiscal wire amounts require decimal strings")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("fiscal wire amount is not a decimal") from error
    if not parsed.is_finite():
        raise ValueError("fiscal wire amount must be finite")
    return parsed


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical(item) for item in value]
    return value


def fiscal_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class FiscalReadRequestV2(FiscalTransportModel):
    contract_version: Literal["fundamental.fiscal-statements.v2"] = (
        "fundamental.fiscal-statements.v2"
    )
    manifest_digest: Digest
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    frequency: Literal["quarter", "ttm"]


class ArtifactRefV1(FiscalTransportModel):
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1)
    role: str = Field(min_length=1)


def require_fiscal_ref(ref: ArtifactRefV1, role: str) -> None:
    if ref.role != role or ref.media_type != "application/json":
        raise ValueError("fiscal release requires its exact JSON artifact role")


class FiscalPublishV2(FiscalTransportModel):
    candidate_ref: ArtifactRefV1
    decision_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_refs(self) -> FiscalPublishV2:
        require_fiscal_ref(self.candidate_ref, "fiscal-statement-candidate-v3")
        require_fiscal_ref(self.decision_ref, "fiscal-display-decision-v2")
        return self


class FiscalDurationPeriodV1(FiscalTransportModel):
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


class FiscalInstantPeriodV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["instant"] = "instant"
    instant: date
    fiscal_year: int
    fiscal_period: Literal["Q1", "Q2", "Q3", "FY", "TTM"]


FiscalPeriodV1 = Annotated[
    FiscalDurationPeriodV1 | FiscalInstantPeriodV1,
    Field(discriminator="kind"),
]


class FiscalPeriodTargetV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    period_id: str
    period: FiscalPeriodV1
    cutoff_at: AwareDatetime
    source_binding_digest: Digest


class FiscalQuarterColumnsV1(FiscalTransportModel):
    frequency: Literal["quarter"] = "quarter"
    periods: tuple[FiscalPeriodTargetV1, ...] = Field(min_length=1)


class FiscalTtmWindowV1(FiscalTransportModel):
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


class FiscalTtmColumnsV1(FiscalTransportModel):
    frequency: Literal["ttm"] = "ttm"
    windows: tuple[FiscalTtmWindowV1, ...] = Field(min_length=1)


FiscalColumnsV1 = Annotated[
    FiscalQuarterColumnsV1 | FiscalTtmColumnsV1, Field(discriminator="frequency")
]


class FiscalReadBindingV2(FiscalTransportModel):
    manifest_digest: Digest
    approved: FiscalPublishV2
    projection_digest: Digest
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    columns: FiscalColumnsV1
    selected_period_set_digest: Digest

    @model_validator(mode="after")
    def exact_period_set(self) -> FiscalReadBindingV2:
        if self.selected_period_set_digest != fiscal_digest(self.columns):
            raise ValueError("fiscal read selected period set differs")
        return self


FiscalStatement = Literal["income_statement", "balance_sheet", "cash_flow"]

FiscalFrequency = Literal["quarter", "ttm"]

FiscalAvailability = Literal["reported", "derived", "unavailable", "conflict"]


class QualityStatus(str, Enum):
    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    ABSTAIN = "abstain"
    ERROR = "error"


class FiscalReportingBasisV1(FiscalTransportModel):
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


class FiscalBasisObservationV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    observation_digest: Digest


class FiscalBasisFilingV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    accession_number: str
    primary_document_sha256: Digest
    accepted_at: AwareDatetime
    disclosure_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    amends_accession: str | None = None
    supersedes_accession: str | None = None


class FiscalComparativePairV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    original_id: str
    comparative_id: str


class FiscalRevisionBridgeV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    observations: tuple[FiscalBasisObservationV1, ...] = Field(min_length=2)
    disclosure_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)


class FiscalRevisionBasisProofV1(FiscalTransportModel):
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


class FiscalPrecisionIntervalV1(FiscalTransportModel):
    @field_validator("lower", "upper", mode="before")
    @classmethod
    def decimal_wire_boundary(cls, value: object) -> Decimal | None:
        return _wire_decimal(value)

    @field_serializer("lower", "upper", when_used="json")
    def decimal_wire(self, value: Decimal) -> str:
        return format(value, "f")

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


class FiscalInputEdgeV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    input_id: str
    coefficient: Literal[-1, 1]


class FiscalCandidateDecisionV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    outcome: Literal["selected", "superseded", "equivalent_duplicate", "rejected"]
    reason: str


class FiscalValueNodeV1(FiscalTransportModel):
    @field_validator("value", mode="before")
    @classmethod
    def decimal_wire_boundary(cls, value: object) -> Decimal | None:
        return _wire_decimal(value)

    @field_serializer("value", when_used="json")
    def decimal_wire(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

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


class OriginalFiscalRevisionV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["original"] = "original"


class AmendedFiscalRevisionV1(FiscalTransportModel):
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


class UnsupportedDurationV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unsupported_duration"] = "unsupported_duration"
    start: date
    end: date
    reason: str


class ReportedInstantV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_instant"] = "reported_instant"
    instant: date


class ReportedFiscalYearV1(FiscalTransportModel):
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


class ReportedQuarterV1(FiscalTransportModel):
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


class ReportedYtdV1(FiscalTransportModel):
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


FiscalReportedPeriodV1 = Annotated[
    ReportedQuarterV1
    | ReportedYtdV1
    | ReportedFiscalYearV1
    | ReportedInstantV1
    | UnsupportedDurationV1,
    Field(discriminator="kind"),
]


class FiscalSourceLocatorV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    primary_document_sha256: Digest
    context_id: str
    fact_index: int = Field(ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)


class FiscalObservationV1(FiscalTransportModel):
    @field_serializer("value", when_used="json")
    def decimal_wire(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

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
        return _wire_decimal(value)

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


class FiscalSourceDocumentV1(FiscalTransportModel):
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    primary_document_url: str = Field(min_length=1)
    primary_document_sha256: Digest
    archive_member_sha256: Digest


class FiscalSourceInspectionV1(FiscalTransportModel):
    source_validation_ref: ArtifactRefV1
    source_document: FiscalSourceDocumentV1
    validation_kind: Literal["complete_matched", "complete_refused"]
    source_binding_digest: Digest
    raw_report_digest: Digest
    parser_action_refs: tuple[ArtifactRefV1, ...]
    witness_ref: ArtifactRefV1 | None
    classification_refs: tuple[ArtifactRefV1, ...]
    mapping_ref: ArtifactRefV1
    mapping_approval_ref: ArtifactRefV1


class FiscalReconciliationV1(FiscalTransportModel):
    @field_validator("residual", mode="before")
    @classmethod
    def decimal_wire_boundary(cls, value: object) -> Decimal | None:
        return _wire_decimal(value)

    @field_serializer("residual", when_used="json")
    def decimal_wire(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

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


class FiscalCashContinuityV1(FiscalTransportModel):
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


class FiscalDisplayGraphV1(FiscalTransportModel):
    nodes: tuple[FiscalValueNodeV1, ...]
    observations: tuple[FiscalObservationV1, ...]
    source_uses: tuple[FiscalSourceInspectionV1, ...]
    reconciliations: tuple[FiscalReconciliationV1, ...]
    cash_continuities: tuple[FiscalCashContinuityV1, ...]


Aggregation = Literal["additive_flow", "instant", "cash_opening", "cash_closing"]


class FiscalRowPolicyV1(FiscalTransportModel):
    model_config = ConfigDict(frozen=True)

    row_id: StatementRowId
    statement: Literal["income_statement", "balance_sheet", "cash_flow"]
    label: str
    aggregation: Aggregation


class FiscalMissingCellV1(FiscalTransportModel):
    kind: Literal["unavailable", "conflict"]
    node_id: str
    reason_code: str


class FiscalReportedCellV1(FiscalTransportModel):
    kind: Literal["reported"] = "reported"
    node_id: str
    decimal: str = Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
    source_observation_ids: tuple[str, ...] = Field(min_length=1)


class FiscalDerivedCellV1(FiscalTransportModel):
    kind: Literal["derived"] = "derived"
    node_id: str
    decimal: str = Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


FiscalCellV1 = Annotated[
    FiscalReportedCellV1 | FiscalDerivedCellV1 | FiscalMissingCellV1,
    Field(discriminator="kind"),
]


class FiscalDisplayRowV1(FiscalTransportModel):
    row: FiscalRowPolicyV1
    cells: tuple[FiscalCellV1, ...] = Field(min_length=1)


class FiscalReadResultV2(FiscalTransportModel):
    contract_version: Literal["fundamental.fiscal-statements.v2"] = (
        "fundamental.fiscal-statements.v2"
    )
    binding: FiscalReadBindingV2
    rows: tuple[FiscalDisplayRowV1, ...]
    evidence: FiscalDisplayGraphV1
    supported_history_threshold: None = None
    valuation_eligibility: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def exact_graph_and_cells(self) -> FiscalReadResultV2:
        nodes = {node.node_id: node for node in self.evidence.nodes}
        observations = {
            item.observation_id: item for item in self.evidence.observations
        }
        if len(nodes) != len(self.evidence.nodes) or len(observations) != len(
            self.evidence.observations
        ):
            raise ValueError("fiscal transport repeats a graph identity")
        sources = {
            item.source_validation_ref.artifact_id: item
            for item in self.evidence.source_uses
        }
        if len(sources) != len(self.evidence.source_uses) or any(
            item.source_document.issuer_id != self.binding.scope.issuer_id
            for item in sources.values()
        ):
            raise ValueError("fiscal transport source identity differs")
        for observation in observations.values():
            source = sources.get(observation.source_artifact_id)
            if source is None or (
                observation.source_binding_digest != source.source_binding_digest
                or observation.issuer_id != source.source_document.issuer_id
                or observation.basis.issuer_id != source.source_document.issuer_id
                or observation.accession_number
                != source.source_document.accession_number
                or observation.source_locator.primary_document_sha256
                != source.source_document.archive_member_sha256
            ):
                raise ValueError("fiscal transport observation source differs")
        for node in nodes.values():
            if (
                any(
                    edge.input_id not in nodes and edge.input_id not in observations
                    for edge in (*node.input_edges, *node.verification_edges)
                )
                or any(identity not in nodes for identity in node.verification_node_ids)
                or any(
                    identity not in observations
                    for identity in (
                        *node.source_observation_ids,
                        *node.verification_observation_ids,
                    )
                )
            ):
                raise ValueError("fiscal transport graph has an unresolved dependency")
        columns = self.binding.columns
        count = (
            len(columns.periods)
            if isinstance(columns, FiscalQuarterColumnsV1)
            else len(columns.windows)
        )
        if len({row.row.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("fiscal transport repeats a row")
        for row in self.rows:
            if len(row.cells) != count:
                raise ValueError(
                    "fiscal transport row differs from its selected columns"
                )
            for cell in row.cells:
                root = nodes.get(cell.node_id)
                if (
                    root is None
                    or root.row_id != row.row.row_id
                    or root.frequency != columns.frequency
                    or root.availability != cell.kind
                ):
                    raise ValueError(
                        "fiscal transport cell differs from its graph root"
                    )
                if isinstance(cell, FiscalReportedCellV1 | FiscalDerivedCellV1) and (
                    root.value is None or cell.decimal != format(root.value, "f")
                ):
                    raise ValueError(
                        "fiscal transport decimal differs from its source node"
                    )
                if (
                    isinstance(cell, FiscalReportedCellV1)
                    and cell.source_observation_ids != root.source_observation_ids
                ):
                    raise ValueError("fiscal reported cell source differs")
                if (
                    isinstance(cell, FiscalMissingCellV1)
                    and cell.reason_code != root.reason_code
                ):
                    raise ValueError("fiscal missing cell reason differs")
        if any(
            identity not in nodes
            for item in self.evidence.reconciliations
            for identity in item.input_node_ids
        ) or any(
            identity not in nodes
            for item in self.evidence.cash_continuities
            for identity in item.input_node_ids
        ):
            raise ValueError("fiscal transport reconciliation has an unresolved node")
        return self
