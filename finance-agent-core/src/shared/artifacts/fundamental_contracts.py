"""Lossless public Fundamental report transport contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

CanonicalDecimal = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$",
    ),
]
FundamentalQualityStatus = Literal[
    "verified", "provisional", "degraded", "unsupported", "abstain", "error"
]


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
    value: str | Annotated[bool, Field(strict=True)] | FundamentalMissingValueV1
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
    accounting_evidence: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


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


class FundamentalForwardReferenceProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str
    source_url: str
    source_content_hash: str
    citation: str
    license_reference: str


class FundamentalManualProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    author: str
    modified_at: datetime
    reason: str
    automatic_preparation_digest: str
    forward_reference: FundamentalForwardReferenceProvenanceV1 | None = None


class FundamentalAssumptionEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    value: CanonicalDecimal
    method: Literal["derived", "approved_source", "approved_policy", "manual"]
    formula: str
    fact_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    policy_version: str
    as_of: datetime
    editable: bool = True
    manual_provenance: FundamentalManualProvenanceV1 | None = None


class FundamentalHistoricalMetricV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    metric_id: str
    fiscal_year: int
    value: CanonicalDecimal
    unit: str
    formula: str
    fact_ids: tuple[str, ...]
    source_refs: tuple[str, ...] = ()
    period_end: str


class FundamentalHistoricalMetricsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_id: str
    profile_digest: str
    metrics: tuple[FundamentalHistoricalMetricV1, ...] = ()
    quality_status: FundamentalQualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    working_capital_assessments: tuple[dict[str, JsonValue], ...] = Field(
        default_factory=tuple, exclude_if=lambda value: not value
    )
    working_capital_inputs: tuple[dict[str, JsonValue], ...] = Field(
        default_factory=tuple, exclude_if=lambda value: not value
    )


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
    historical_metrics: FundamentalHistoricalMetricsV1
    assumptions_evidence: tuple[FundamentalAssumptionEvidenceV1, ...] = ()
    input: dict[str, JsonValue] | None = None
    preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    equity_dilution: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    conditional_capital: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    conditional_quote: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    conditional_operating: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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
    mapping_version: str | None = Field(default=None, min_length=1)
    facts: tuple[FundamentalCanonicalFactV1, ...] = ()


class FundamentalTraceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
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


class FundamentalCalculationNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: str
    formula: str
    inputs: tuple[str, ...] = ()
    value: CanonicalDecimal | None = None
    unit: str
    trace: FundamentalTraceV1


class FundamentalServiceEvidenceReferenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str
    artifact_type: Literal["calculation_evidence", "uncertainty_evidence"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["application/json"] = "application/json"


class FundamentalFiscalPeriodV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fiscal_year: int


class FundamentalFiscalPeriodSelectorV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["fundamental.fiscal-period-selector.v1"] = (
        "fundamental.fiscal-period-selector.v1"
    )
    mode: Literal["latest_complete", "explicit_periods"]
    count: int | None = None
    periods: tuple[FundamentalFiscalPeriodV1, ...] = ()


class FundamentalResolvedFiscalPeriodV1(FundamentalFiscalPeriodV1):
    period_start: date
    period_end: date
    available_at: datetime


class FundamentalCalculationTraceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valuation_timestamp: datetime
    fiscal_period_selector: FundamentalFiscalPeriodSelectorV1
    resolved_fiscal_periods: tuple[FundamentalResolvedFiscalPeriodV1, ...] = ()
    source_selection_policy: str
    source_selection_policy_version: str
    snapshot_id: str
    snapshot_manifest_digest: str
    data_release_manifest_digest: str | None = None
    fact_ids: tuple[str, ...]
    source_content_hashes: tuple[str, ...]
    policy_id: str
    policy_version: str
    policy_digest: str
    model_id: str
    model_version: str
    assumptions_digest: str
    calculation_version: str


class FundamentalPolicyResolutionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["fundamental.v1"]
    policy_id: str
    policy_version: str
    policy_digest: str
    selection_mode: Literal["pinned", "exploratory_active"]
    resolved_fields: dict[str, JsonValue]
    precedence: dict[str, Literal["caller", "policy"]]
    input_digest: str


class FundamentalCalculationResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["fundamental.v1"]
    calculation_version: str
    calculation_status: Literal[
        "completed", "abstained", "rejected", "unavailable", "error"
    ]
    quality_status: FundamentalQualityStatus
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intrinsic_value: CanonicalDecimal | None = None
    per_share_value: CanonicalDecimal | None = None
    nodes: tuple[FundamentalCalculationNodeV1, ...] = ()
    assumptions: dict[str, JsonValue]
    policy_id: str | None = None
    model_version: str
    policy_version: str | None = None
    policy_resolution: FundamentalPolicyResolutionV1 | None = None
    trace: FundamentalCalculationTraceV1 | None = None
    artifact_references: tuple[FundamentalServiceEvidenceReferenceV1, ...] = ()
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    snapshot_id: str
    valuation_timestamp: datetime
    evaluated_at: datetime
    correlation_id: str


class FundamentalConvergenceDiagnosticsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    minimum_valid_samples: int | None = None
    invalid_ratio: CanonicalDecimal | None = None
    converged: bool | None = None


class FundamentalConditionalQuantileBasisV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conditioning: Literal["retained_base_joint_hypotheses"]
    joint_scenarios_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    conditioning_assumptions_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: Literal["conditional-fcff-monte-carlo-policy-v1"]
    sampled_paths: tuple[
        Literal["assumptions.forecast.revenue_growth[0]"],
        Literal["assumptions.forecast.operating_margin[0]"],
        Literal["assumptions.terminal_growth"],
    ]
    hypothesis_probabilities: Literal["not_assigned"]


class FundamentalUncertaintyResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: FundamentalQualityStatus
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base: FundamentalCalculationResultV1
    scenario_results: tuple[FundamentalCalculationResultV1, ...] = ()
    sensitivity: dict[str, tuple[CanonicalDecimal, ...]] = Field(default_factory=dict)
    requested_samples: int = 0
    valid_samples: int = 0
    invalid_samples: int = 0
    invalid_reasons: dict[str, int] = Field(default_factory=dict)
    invalid_draw_policy: str | None = None
    seed: (
        Annotated[str, Field(strict=True, pattern=r"^(?:0|-?[1-9][0-9]*)$")] | None
    ) = None
    sampler_version: str | None = None
    quantiles: dict[str, CanonicalDecimal] = Field(default_factory=dict)
    quantile_basis: FundamentalConditionalQuantileBasisV1 | None = None
    quantile_contract: dict[str, str] = Field(default_factory=dict)
    convergence_diagnostics: FundamentalConvergenceDiagnosticsV1 = Field(
        default_factory=FundamentalConvergenceDiagnosticsV1
    )
    dominant_drivers: tuple[str, ...] = ()
    artifact_references: tuple[FundamentalServiceEvidenceReferenceV1, ...] = ()


FundamentalServiceResultV1 = (
    FundamentalCalculationResultV1 | FundamentalUncertaintyResultV1
)


class FundamentalBoundFactsV1(FundamentalFactsReadResultV1):
    fact_ids: tuple[str, ...]


class FundamentalFactsQualityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    facts_status: FundamentalQualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    rejected_fact_ids: tuple[str, ...] = ()


class FundamentalReportHashesV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_digest: str | None = None
    result_hash: str | None = None
    snapshot_manifest_digest: str
    data_release_manifest_digest: str | None = None
    source_content_hashes: tuple[str, ...] = ()


class FundamentalValuationEvidenceV1(FundamentalValuationEvidenceReadResultV1):
    projection_type: Literal["valuation_evidence"]
    snapshot_timestamp: datetime
    fact_ids: tuple[str, ...]
    provenance: dict[str, JsonValue]
    quality: FundamentalFactsQualityV1
    hashes: FundamentalReportHashesV1


class FundamentalValuationQualityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input: dict[str, JsonValue]
    validation_status: FundamentalQualityStatus
    facts_status: FundamentalQualityStatus
    calculation_status: FundamentalQualityStatus
    issue_codes: tuple[str, ...] = ()


class FundamentalValuationReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    projection_type: Literal["valuation"]
    contract_version: Literal["fundamental.v1"]
    calculation_version: str
    calculation_status: Literal[
        "completed", "abstained", "rejected", "unavailable", "error"
    ]
    quality_status: FundamentalQualityStatus
    input_digest: str
    result_hash: str
    service_result: FundamentalServiceResultV1
    correlation_id: str
    facts: FundamentalBoundFactsV1 | FundamentalValuationEvidenceV1
    snapshot_id: str
    snapshot_manifest_digest: str
    fact_ids: tuple[str, ...]
    valuation_trace: FundamentalCalculationTraceV1
    provenance: dict[str, JsonValue]
    quality: FundamentalValuationQualityV1
    hashes: FundamentalReportHashesV1
    valuation_input: dict[str, JsonValue]
    automatic_preparation: FundamentalValuationPreparationResultV1 | None = None


class FundamentalFactsOnlyReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    projection_type: Literal["facts_only"]
    contract_version: Literal["fundamental.v1"]
    valuation_status: Literal["not_requested"]
    snapshot_id: str
    snapshot_timestamp: datetime
    snapshot_manifest_digest: str
    fact_ids: tuple[str, ...]
    facts: FundamentalBoundFactsV1
    snapshot_selector: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    quality: FundamentalFactsQualityV1
    hashes: FundamentalReportHashesV1
    issue_codes: tuple[str, ...] = ()


class FundamentalPreparationOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    projection_type: Literal["preparation_outcome"]
    contract_version: Literal["fundamental.v1"]
    valuation_status: Literal["requires_input", "abstained", "unsupported"]
    quality_status: FundamentalQualityStatus
    automatic_preparation: FundamentalValuationPreparationResultV1
    identity: FundamentalIdentityV1
    snapshot_selector: dict[str, JsonValue]
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    reason: str | None = None


class FundamentalServiceFailureV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    message: str
    retryable: bool


class FundamentalDegradedReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    projection_type: Literal["degraded"]
    contract_version: Literal["fundamental.v1"]
    valuation_status: Literal["service_unavailable"]
    quality_status: Literal["degraded"]
    issue_codes: tuple[str, ...]
    service_failure: FundamentalServiceFailureV1


FundamentalServiceArtifactV1 = Annotated[
    FundamentalValuationReportV1
    | FundamentalFactsOnlyReportV1
    | FundamentalPreparationOutcomeV1
    | FundamentalDegradedReportV1,
    Field(discriminator="projection_type"),
]
