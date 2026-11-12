"""Deterministic evidence-to-input preparation for released FCFF models."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .annual_history import (
    AnnualHistoryError,
    AnnualHistoryPeriodV1,
    AnnualHistoryV1,
    resolve_annual_history,
)
from .contracts import (
    AssumptionsV1,
    CanonicalFactV1,
    CapitalBridgeAssumptionsV1,
    FiscalPeriodV1,
    FiscalPeriodSelectorV1,
    ForecastAssumptionsV1,
    ProvenanceInputV1,
    QualityInputV1,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
    StrictModel,
    TraceV1,
    UncertaintyV1,
    ValuationContextV1,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from .numerical_policy import using_valuation_context
from .equity_award_evidence import (
    EquityDilutionEvidenceV1,
    verify_dilution_fact_bindings,
)
from .equity_dilution import (
    DilutionError,
    TreasuryStockResultV1,
    compute_treasury_stock_dilution,
)
from .original_issuer import IssuerOperatingSourceV1
from .serialization import sha256_digest
from .uncertainty_policy import (
    DEFAULT_UNCERTAINTY_POLICY_VERSION,
    build_default_uncertainty,
)
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    select_released_facts,
    valuation_requirements_profile,
    composite_working_capital_requirements_profile,
)
from .working_capital import (
    CompositeWorkingCapitalAssessmentV1,
    CompositeWorkingCapitalInputV1,
    WORKING_CAPITAL_FIELDS,
    canonical_working_capital_inputs,
)

_ZERO_TOLERANCE = Decimal("0.000000001")
_MIN_REVENUE_GROWTH = Decimal("-0.90")
_MAX_REVENUE_GROWTH = Decimal("1.00")
_MIN_REINVESTMENT_RATE = Decimal("-1.00")
_MAX_REINVESTMENT_RATE = Decimal("1.00")
_FORECAST_PERIODS = 5
FORECAST_COMPOSER_VERSION = "fcff-forecast-composer-v5"


class PreparationError(ValueError):
    """A deterministic preparation gate failed."""

    def __init__(self, code: str, message: str, *, missing: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.missing = missing


class HistoricalMetricV1(StrictModel):
    """One derived historical metric with exact formula and fact lineage."""

    metric_id: str = Field(min_length=1)
    fiscal_year: int = Field(ge=1900, le=2200)
    value: Decimal
    unit: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = ()
    period_end: str = Field(min_length=1)


class HistoricalMetricsV1(StrictModel):
    """Derived annual metrics and their quality disposition."""

    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: tuple[HistoricalMetricV1, ...] = ()
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    working_capital_assessments: tuple[CompositeWorkingCapitalAssessmentV1, ...] = (
        Field(default=(), exclude_if=lambda value: not value)
    )
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


class ApprovedMarketPolicyInputsV1(StrictModel):
    """Explicit, source-bound non-SEC inputs required by FCFF preparation."""

    policy_version: str = Field(min_length=1)
    capital_weight_basis: Literal["market_observed", "approved_policy"] = (
        "approved_policy"
    )
    risk_free_rate: Decimal | None = None
    beta: Decimal | None = None
    equity_risk_premium: Decimal | None = None
    pre_tax_cost_of_debt: Decimal | None = None
    debt_weight: Decimal | None = None
    equity_weight: Decimal | None = None
    terminal_growth: Decimal | None = None
    evidence: dict[str, TraceV1] = Field(default_factory=dict)
    evidence_methods: dict[str, Literal["observed_source", "approved_policy"]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    @using_valuation_context
    def evidence_matches_values(self) -> ApprovedMarketPolicyInputsV1:
        required = (
            "risk_free_rate",
            "beta",
            "equity_risk_premium",
            "pre_tax_cost_of_debt",
            "debt_weight",
            "equity_weight",
            "terminal_growth",
        )
        missing = tuple(
            field
            for field in required
            if getattr(self, field) is None or field not in self.evidence
        )
        if missing:
            raise ValueError(
                "approved market and policy inputs require source evidence: "
                + ", ".join(missing)
            )
        methods = {
            field: self.evidence_methods.get(field, "approved_policy")
            for field in required
        }
        weight_methods = {methods[field] for field in ("debt_weight", "equity_weight")}
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
        if self.debt_weight is not None and self.equity_weight is not None:
            if not all(
                Decimal("0") <= value <= Decimal("1")
                for value in (self.debt_weight, self.equity_weight)
            ):
                raise ValueError("market policy weights must be between zero and one")
            if self.debt_weight + self.equity_weight != Decimal("1"):
                raise ValueError("market policy weights must sum to one")
        if self.terminal_growth is not None and not (
            Decimal("-1") < self.terminal_growth < Decimal("1")
        ):
            raise ValueError("terminal growth must be between -100% and 100%")
        return self


class AssumptionEvidenceV1(StrictModel):
    """Reviewable evidence for one generated assumption path."""

    path: str = Field(min_length=1)
    value: Decimal
    method: Literal["derived", "approved_source", "approved_policy", "manual"]
    formula: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    policy_version: str = Field(min_length=1)
    as_of: datetime
    editable: bool = True
    manual_provenance: "ManualProvenanceV1 | None" = None

    @model_validator(mode="after")
    def timestamp_has_timezone(self) -> AssumptionEvidenceV1:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("assumption evidence as_of must include a timezone")
        return self

    @model_validator(mode="after")
    def manual_method_has_provenance(self) -> AssumptionEvidenceV1:
        if self.method == "manual" and self.manual_provenance is None:
            raise ValueError("manual assumption evidence requires provenance")
        if self.method != "manual" and self.manual_provenance is not None:
            raise ValueError(
                "automatic assumption evidence cannot include manual provenance"
            )
        return self


class ManualProvenanceV1(StrictModel):
    """Human attribution for one supported assumption override."""

    author: str = Field(min_length=1)
    modified_at: datetime
    reason: str = Field(min_length=1)
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    forward_reference: "ForwardReferenceProvenanceV1 | None" = None

    @model_validator(mode="after")
    def timestamp_has_timezone(self) -> ManualProvenanceV1:
        if self.modified_at.tzinfo is None or self.modified_at.utcoffset() is None:
            raise ValueError("manual provenance modified_at must include a timezone")
        return self


class ForwardReferenceProvenanceV1(StrictModel):
    """Citation retained when a user applies optional forward evidence."""

    claim_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1, max_length=2048)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation: str = Field(min_length=20, max_length=8192)
    license_reference: str = Field(min_length=1, max_length=2048)


AssumptionEvidenceV1.model_rebuild()
ManualProvenanceV1.model_rebuild()


class AutomaticValuationPreparationV1(StrictModel):
    """Complete or explicitly blocked service-owned valuation preparation."""

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    status: Literal["prepared", "requires_input", "abstained", "unsupported"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    quality_status: QualityStatus
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    historical_metrics: HistoricalMetricsV1
    assumptions_evidence: tuple[AssumptionEvidenceV1, ...] = ()
    input: ValuationInputV1 | None = None
    equity_dilution: TreasuryStockResultV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def status_matches_input(self) -> AutomaticValuationPreparationV1:
        if (self.status == "prepared") != (self.input is not None):
            raise ValueError("prepared status must match the presence of input")
        if (
            self.quality_status is QualityStatus.VERIFIED
            and "HISTORY_THRESHOLD_UNVALIDATED" in self.issue_codes
        ):
            raise ValueError("unvalidated history cannot be marked verified")
        return self


class ManualValuationOverrideRequestV1(StrictModel):
    """Request to edit one generated assumption while retaining its evidence."""

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    preparation: AutomaticValuationPreparationV1
    path: str = Field(min_length=1)
    value: Decimal
    provenance: ManualProvenanceV1


def _metric(
    metric_id: str,
    period: AnnualHistoryPeriodV1,
    value: Decimal,
    formula: str,
    facts: Iterable[CanonicalFactV1],
    *,
    unit: str = "ratio",
) -> HistoricalMetricV1:
    fact_items = tuple(facts)
    return HistoricalMetricV1(
        metric_id=metric_id,
        fiscal_year=period.fiscal_year,
        value=value,
        unit=unit,
        formula=formula,
        fact_ids=tuple(item.fact_id for item in fact_items),
        source_refs=tuple(item.source.content_hash for item in fact_items),
        period_end=period.period_end.isoformat(),
    )


@using_valuation_context
def derive_historical_metrics(
    history: AnnualHistoryV1,
) -> HistoricalMetricsV1:
    """Derive reviewed FCFF historical metrics without numeric placeholders."""

    if history.quality is QualityStatus.ABSTAIN:
        return HistoricalMetricsV1(
            profile_id=history.requirements_profile_id,
            profile_digest=history.requirements_profile_digest,
            quality_status=QualityStatus.ABSTAIN,
            working_capital_assessments=history.working_capital_assessments,
            working_capital_inputs=(),
            issue_codes=history.issue_codes,
            missing_evidence=tuple(
                f"{year}:{field}" for year, field in history.missing_fields
            ),
        )

    metrics: list[HistoricalMetricV1] = []
    issue_codes = list(history.issue_codes)
    missing: list[str] = []
    for index, period in enumerate(history.periods):
        candidates = {
            field: period.fact(field)
            for field in (
                "revenue",
                "operating_income",
                "income_before_tax",
                "income_tax_expense",
                "capital_expenditure",
                "depreciation_and_amortization",
                *(WORKING_CAPITAL_FIELDS if period.working_capital is None else ()),
            )
        }
        absent = tuple(name for name, fact in candidates.items() if fact is None)
        if absent:
            missing.extend(f"{period.fiscal_year}:{name}" for name in absent)
            continue
        fields = {name: fact for name, fact in candidates.items() if fact is not None}
        values = {
            name: fact.value
            for name, fact in fields.items()
            if isinstance(fact.value, Decimal)
        }
        if len(values) != len(fields):
            issue_codes.append("METRIC_NON_NUMERIC_VALUE")
            continue
        revenue = values["revenue"]
        operating_income = values["operating_income"]
        income_before_tax = values["income_before_tax"]
        tax_expense = values["income_tax_expense"]
        if revenue <= _ZERO_TOLERANCE:
            issue_codes.append("METRIC_REVENUE_NON_POSITIVE")
            continue
        if abs(income_before_tax) <= _ZERO_TOLERANCE:
            issue_codes.append("METRIC_TAX_DENOMINATOR_UNSTABLE")
            continue
        tax_rate = tax_expense / income_before_tax
        nopat = operating_income * (Decimal("1") - tax_rate)
        metrics.extend(
            (
                _metric(
                    "operating_margin",
                    period,
                    operating_income / revenue,
                    "operating_income / revenue",
                    (fields["operating_income"], fields["revenue"]),
                ),
                _metric(
                    "normalized_tax_rate",
                    period,
                    tax_rate,
                    "income_tax_expense / income_before_tax",
                    (fields["income_tax_expense"], fields["income_before_tax"]),
                ),
                _metric(
                    "nopat",
                    period,
                    nopat,
                    "operating_income * (1 - normalized_tax_rate)",
                    (
                        fields["operating_income"],
                        fields["income_tax_expense"],
                        fields["income_before_tax"],
                    ),
                    unit="currency",
                ),
            )
        )
        if index == 0:
            continue
        previous = history.periods[index - 1]
        previous_revenue = previous.fact("revenue")
        if previous_revenue is None or not isinstance(previous_revenue.value, Decimal):
            missing.append(f"{period.fiscal_year}:prior_revenue")
            continue
        if previous_revenue.value <= _ZERO_TOLERANCE:
            issue_codes.append("METRIC_GROWTH_DENOMINATOR_UNSTABLE")
            continue
        working_capital_fields = (
            WORKING_CAPITAL_FIELDS if previous.working_capital is None else ()
        )
        previous_candidates = {
            name: previous.fact(name) for name in working_capital_fields
        }
        absent_previous = tuple(
            name for name, fact in previous_candidates.items() if fact is None
        )
        if absent_previous:
            missing.extend(
                f"{period.fiscal_year}:prior_{name}" for name in absent_previous
            )
            continue
        previous_fields = {
            name: fact for name, fact in previous_candidates.items() if fact is not None
        }
        previous_values = {
            name: fact.value
            for name, fact in previous_fields.items()
            if isinstance(fact.value, Decimal)
        }
        if len(previous_values) != len(previous_fields):
            issue_codes.append("METRIC_NON_NUMERIC_VALUE")
            continue
        current_working_capital = (
            period.working_capital.value
            if period.working_capital is not None
            else (
                values["operating_current_receivables"]
                + values["inventory"]
                + values["contract_assets"]
                - values["operating_current_payables"]
                - values["accrued_operating_liabilities"]
                - values["deferred_revenue"]
            )
        )
        previous_working_capital = (
            previous.working_capital.value
            if previous.working_capital is not None
            else (
                previous_values["operating_current_receivables"]
                + previous_values["inventory"]
                + previous_values["contract_assets"]
                - previous_values["operating_current_payables"]
                - previous_values["accrued_operating_liabilities"]
                - previous_values["deferred_revenue"]
            )
        )
        if current_working_capital is None or previous_working_capital is None:
            issue_codes.append("WORKING_CAPITAL_ESTIMATE_UNAVAILABLE")
            continue
        current_working_capital_facts = (
            period.working_capital.source_facts
            if period.working_capital is not None
            else tuple(fields[field] for field in WORKING_CAPITAL_FIELDS)
        )
        previous_working_capital_facts = (
            previous.working_capital.source_facts
            if previous.working_capital is not None
            else tuple(previous_fields[field] for field in WORKING_CAPITAL_FIELDS)
        )
        delta_working_capital = current_working_capital - previous_working_capital
        capex = values["capital_expenditure"]
        depreciation = values["depreciation_and_amortization"]
        if abs(nopat) <= _ZERO_TOLERANCE:
            issue_codes.append("METRIC_REINVESTMENT_DENOMINATOR_UNSTABLE")
            continue
        net_reinvestment = capex - depreciation + delta_working_capital
        realized_fact_candidates = (
            fields["operating_income"],
            fields["income_tax_expense"],
            fields["income_before_tax"],
            fields["capital_expenditure"],
            fields["depreciation_and_amortization"],
            *current_working_capital_facts,
            *previous_working_capital_facts,
        )
        realized_facts = realized_fact_candidates
        metrics.extend(
            (
                _metric(
                    "revenue_growth",
                    period,
                    revenue / previous_revenue.value - Decimal("1"),
                    "revenue / prior_revenue - 1",
                    (fields["revenue"], previous_revenue),
                ),
                _metric(
                    "delta_operating_working_capital",
                    period,
                    delta_working_capital,
                    "operating_working_capital - prior_operating_working_capital",
                    (
                        *current_working_capital_facts,
                        *previous_working_capital_facts,
                    ),
                    unit="currency",
                ),
                _metric(
                    "reinvestment_rate",
                    period,
                    net_reinvestment / nopat,
                    (
                        "(capital_expenditure - depreciation_and_amortization + "
                        "delta_operating_working_capital) / nopat"
                    ),
                    (
                        fields["capital_expenditure"],
                        fields["depreciation_and_amortization"],
                        *current_working_capital_facts,
                        fields["operating_income"],
                        fields["income_tax_expense"],
                        fields["income_before_tax"],
                        *previous_working_capital_facts,
                    ),
                ),
                _metric(
                    "realized_fcff",
                    period,
                    nopat - net_reinvestment,
                    "nopat - (capital_expenditure - depreciation_and_amortization + delta_operating_working_capital)",
                    realized_facts,
                    unit="currency",
                ),
            )
        )
    if missing:
        issue_codes.append("METRIC_REQUIRED_FIELDS_MISSING")
    status = QualityStatus.PROVISIONAL
    if any(
        code.endswith("UNSTABLE") or code == "METRIC_NON_NUMERIC_VALUE"
        for code in issue_codes
    ):
        status = QualityStatus.ABSTAIN
    return HistoricalMetricsV1(
        profile_id=history.requirements_profile_id,
        profile_digest=history.requirements_profile_digest,
        metrics=tuple(metrics),
        quality_status=status,
        issue_codes=tuple(dict.fromkeys(issue_codes)),
        missing_evidence=tuple(sorted(set(missing))),
        working_capital_assessments=history.working_capital_assessments,
    )


def _latest_fact(
    facts: Iterable[CanonicalFactV1], field: str
) -> CanonicalFactV1 | None:
    matches = tuple(
        fact
        for fact in facts
        if fact.normalized_field == field
        and fact.quality is QualityStatus.VERIFIED
        and isinstance(fact.value, Decimal)
        and fact.context.period_type.value == "instant"
        and fact.instant is not None
    )
    if not matches:
        return None
    latest_period = max(
        instant for fact in matches if (instant := fact.instant) is not None
    )
    period_matches = tuple(fact for fact in matches if fact.instant == latest_period)
    latest_available = max(fact.available_at for fact in period_matches)
    latest = tuple(
        fact for fact in period_matches if fact.available_at == latest_available
    )
    if len({(fact.value, fact.period_end, fact.instant) for fact in latest}) != 1:
        raise PreparationError("CAPITAL_FACT_CONFLICT", f"conflicting {field} facts")
    return min(latest, key=lambda fact: fact.fact_id)


def _assumption_evidence(
    path: str,
    value: Decimal,
    method: Literal["derived", "approved_source", "approved_policy"],
    formula: str,
    *,
    facts: Iterable[CanonicalFactV1] = (),
    trace: TraceV1 | None = None,
    policy_version: str,
    as_of: datetime,
) -> AssumptionEvidenceV1:
    fact_items = tuple(facts)
    return AssumptionEvidenceV1(
        path=path,
        value=value,
        method=method,
        formula=formula,
        fact_ids=tuple(item.fact_id for item in fact_items),
        source_refs=(
            tuple(item.source.content_hash for item in fact_items)
            if trace is None
            else trace.source_refs
        ),
        policy_version=policy_version,
        as_of=as_of,
    )


_FORECAST_OVERRIDE = re.compile(
    r"^assumptions\.forecast\.(revenue_growth|operating_margin|reinvestment_rate)\[(\d+)\]$"
)


def _override_assumptions(
    assumptions: AssumptionsV1,
    *,
    path: str,
    value: Decimal,
) -> AssumptionsV1:
    forecast_match = _FORECAST_OVERRIDE.fullmatch(path)
    if forecast_match:
        if assumptions.forecast is None:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED", "forecast assumptions are unavailable"
            )
        field, index_text = forecast_match.groups()
        values = list(getattr(assumptions.forecast, field))
        index = int(index_text)
        if index >= len(values):
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED", "forecast override index is out of range"
            )
        values[index] = value
        forecast = assumptions.forecast.model_copy(update={field: tuple(values)})
        return assumptions.model_copy(update={"forecast": forecast})

    if path == "assumptions.forecast.base_revenue":
        if assumptions.forecast is None:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED", "forecast assumptions are unavailable"
            )
        return assumptions.model_copy(
            update={
                "forecast": assumptions.forecast.model_copy(
                    update={"base_revenue": value}
                )
            }
        )

    if path == "assumptions.terminal_growth":
        return assumptions.model_copy(update={"terminal_growth": value})

    if path.startswith("assumptions.wacc."):
        if assumptions.wacc is None:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED", "WACC assumptions are unavailable"
            )
        field = path.removeprefix("assumptions.wacc.")
        if field not in assumptions.wacc.model_fields:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED", "WACC override field is unsupported"
            )
        return assumptions.model_copy(
            update={"wacc": assumptions.wacc.model_copy(update={field: value})}
        )

    if path.startswith("assumptions.capital_bridge."):
        if assumptions.capital_bridge is None:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED",
                "capital bridge assumptions are unavailable",
            )
        field = path.removeprefix("assumptions.capital_bridge.")
        if field not in assumptions.capital_bridge.model_fields:
            raise PreparationError(
                "MANUAL_OVERRIDE_UNSUPPORTED",
                "capital bridge override field is unsupported",
            )
        return assumptions.model_copy(
            update={
                "capital_bridge": assumptions.capital_bridge.model_copy(
                    update={field: value}
                )
            }
        )

    raise PreparationError(
        "MANUAL_OVERRIDE_UNSUPPORTED", "assumption path is not editable"
    )


@using_valuation_context
def apply_manual_override(
    preparation: AutomaticValuationPreparationV1,
    *,
    path: str,
    value: Decimal,
    provenance: ManualProvenanceV1,
) -> AutomaticValuationPreparationV1:
    """Apply one supported override and bind it to the automatic preparation."""

    if preparation.status != "prepared" or preparation.input is None:
        raise PreparationError(
            "MANUAL_OVERRIDE_UNAVAILABLE",
            "manual overrides require a prepared valuation input",
        )
    if provenance.automatic_preparation_digest != preparation.preparation_digest:
        raise PreparationError(
            "MANUAL_OVERRIDE_DIGEST_MISMATCH",
            "manual provenance is bound to a different automatic preparation",
        )
    automatic = tuple(
        evidence
        for evidence in preparation.assumptions_evidence
        if evidence.path == path
    )
    if (
        len(automatic) != 1
        or automatic[0].method == "manual"
        or not automatic[0].editable
    ):
        raise PreparationError(
            "MANUAL_OVERRIDE_UNSUPPORTED",
            "assumption path has no unique automatic evidence",
        )
    assumptions = _override_assumptions(
        preparation.input.assumptions, path=path, value=value
    )
    updated_input = preparation.input.model_copy(
        update={
            "assumptions": assumptions,
            "uncertainty": UncertaintyV1(mode="none"),
            "input_digest": None,
            "caller_approval": None,
        }
    ).with_digest()
    if preparation.input.uncertainty.mode == "monte_carlo":
        updated_input = updated_input.model_copy(
            update={
                "uncertainty": build_default_uncertainty(
                    updated_input,
                    historical_metrics=preparation.historical_metrics.metrics,
                    policy_version=(
                        preparation.input.uncertainty.policy_version
                        or DEFAULT_UNCERTAINTY_POLICY_VERSION
                    ),
                )
            }
        ).with_digest()
    manual_evidence = automatic[0].model_copy(
        update={
            "value": value,
            "method": "manual",
            "formula": f"manual override of {path}",
            "source_refs": (
                (provenance.forward_reference.source_content_hash,)
                if provenance.forward_reference is not None
                else automatic[0].source_refs
            ),
            "manual_provenance": provenance,
        }
    )
    updated_evidence = tuple((*preparation.assumptions_evidence, manual_evidence))
    issue_codes = tuple(
        dict.fromkeys((*preparation.issue_codes, "MANUAL_OVERRIDE_APPLIED"))
    )
    payload = {
        "status": preparation.status,
        "model_id": preparation.model_id,
        "model_version": preparation.model_version,
        "profile_id": preparation.profile_id,
        "profile_digest": preparation.profile_digest,
        "policy_id": preparation.policy_id,
        "policy_version": preparation.policy_version,
        "quality_status": preparation.quality_status,
        "issue_codes": issue_codes,
        "missing_evidence": preparation.missing_evidence,
        "historical_metrics": preparation.historical_metrics,
        "assumptions_evidence": updated_evidence,
        "input": updated_input,
    }
    return AutomaticValuationPreparationV1.model_validate(
        {
            **payload,
            "preparation_digest": sha256_digest(
                {
                    **payload,
                    "automatic_preparation_digest": preparation.preparation_digest,
                    "manual_provenance": provenance,
                }
            ),
        }
    )


def _transition_filing_evidence(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
) -> tuple[CanonicalFactV1, ...]:
    """Require transition evidence to remain tied to a filed SEC source."""

    evidence = tuple(
        fact for fact in facts if fact.normalized_field == "filed_operating_evidence"
    )
    if not evidence:
        raise PreparationError(
            "TRANSITION_EVIDENCE_MISSING",
            "transition FCFF requires pinned filing operating evidence",
            missing=("filed_operating_evidence",),
        )
    invalid = tuple(
        fact.fact_id
        for fact in evidence
        if fact.source.source_role is not SourceRole.FILING
        or not fact.accession_number
        or fact.source.accession_number != fact.accession_number
        or fact.period_end > snapshot.valuation_timestamp.date()
        or fact.available_at > snapshot.valuation_timestamp
        or fact.quality is not QualityStatus.VERIFIED
    )
    if invalid:
        raise PreparationError(
            "TRANSITION_EVIDENCE_INVALID",
            (
                "transition evidence must be verified, filed, accession-bound, "
                "and point-in-time eligible"
            ),
            missing=tuple(f"filed_operating_evidence:{fact_id}" for fact_id in invalid),
        )
    return tuple(sorted(evidence, key=lambda fact: fact.fact_id))


@using_valuation_context
def compose_forecast_assumptions(
    history: AnnualHistoryV1,
    metrics: HistoricalMetricsV1,
) -> ForecastAssumptionsV1:
    """Compose the shared #352 operating assumptions without valuation claims."""

    metric_by_name: dict[str, list[HistoricalMetricV1]] = {}
    for metric in metrics.metrics:
        metric_by_name.setdefault(metric.metric_id, []).append(metric)
    growth = [item.value for item in metric_by_name.get("revenue_growth", ())]
    margins = [item.value for item in metric_by_name.get("operating_margin", ())]
    reinvestment = [item.value for item in metric_by_name.get("reinvestment_rate", ())]
    if len(growth) < 2 or len(margins) < 3 or len(reinvestment) < 2:
        raise PreparationError(
            "FORECAST_HISTORY_INSUFFICIENT",
            "forecast requires three margins and two growth/reinvestment periods",
            missing=("forecast_history",),
        )
    latest_revenue = history.periods[-1].fact("revenue")
    assert latest_revenue is not None and isinstance(latest_revenue.value, Decimal)
    mean_growth = sum(growth, Decimal("0")) / Decimal(len(growth))
    mean_margin = sum(margins[-3:], Decimal("0")) / Decimal(min(3, len(margins)))
    mean_reinvestment = sum(reinvestment, Decimal("0")) / Decimal(len(reinvestment))
    if not _MIN_REVENUE_GROWTH <= mean_growth <= _MAX_REVENUE_GROWTH:
        raise PreparationError(
            "FORECAST_GROWTH_OUT_OF_BOUNDS", "mean revenue growth exceeds policy bounds"
        )
    bounded_reinvestment = min(
        _MAX_REINVESTMENT_RATE,
        max(_MIN_REINVESTMENT_RATE, mean_reinvestment),
    )
    forecast_growth = tuple(
        mean_growth * (Decimal(_FORECAST_PERIODS - index) / Decimal(_FORECAST_PERIODS))
        for index in range(_FORECAST_PERIODS)
    )
    return ForecastAssumptionsV1(
        base_revenue=latest_revenue.value,
        revenue_growth=forecast_growth,
        operating_margin=(mean_margin,) * _FORECAST_PERIODS,
        reinvestment_rate=(bounded_reinvestment,) * _FORECAST_PERIODS,
    )


@using_valuation_context
def _prepare_automatic_valuation(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    data_release_manifest_digest: str,
    market_policy: ApprovedMarketPolicyInputsV1 | None = None,
    mapping_version: str = "sec-canonical-mapping-v1",
    equity_dilution_evidence: EquityDilutionEvidenceV1 | None = None,
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...] = (),
) -> AutomaticValuationPreparationV1:
    """Compose a deterministic valuation request or an explicit gate outcome."""

    profile = (
        composite_working_capital_requirements_profile(model_id, operating_only=False)
        if working_capital_inputs
        else valuation_requirements_profile(model_id)
    )
    selected = select_released_facts(
        facts,
        profile=profile,
        snapshot=snapshot,
        valuation_timestamp=snapshot.valuation_timestamp,
        additional_fact_ids=tuple(
            fact_id for item in working_capital_inputs for fact_id in item.fact_ids
        ),
    )
    if any(item.mapping_version != mapping_version for item in working_capital_inputs):
        return _blocked_preparation(
            status="abstained",
            quality=QualityStatus.ABSTAIN,
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            issues=("WORKING_CAPITAL_MAPPING_VERSION_MISMATCH",),
            missing=(),
            facts=selected.facts,
            snapshot=snapshot,
        )
    if selected.missing_fields:
        return _blocked_preparation(
            status="abstained",
            quality=QualityStatus.ABSTAIN,
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            issues=selected.issue_codes,
            missing=selected.missing_fields,
            facts=selected.facts,
            snapshot=snapshot,
        )
    transition_evidence: tuple[CanonicalFactV1, ...] = ()
    if profile.transition_filing_evidence_required:
        try:
            transition_evidence = _transition_filing_evidence(
                selected.facts,
                snapshot=snapshot,
            )
        except PreparationError as error:
            metrics = HistoricalMetricsV1(
                profile_id=profile.profile_id,
                profile_digest=profile.digest,
                quality_status=QualityStatus.ABSTAIN,
                issue_codes=(error.code,),
                missing_evidence=error.missing,
            )
            return _blocked_from_metrics(
                metrics,
                profile=profile,
                model_id=model_id,
                model_version=model_version,
                policy_id=policy_id,
                policy_version=policy_version,
                facts=selected.facts,
                snapshot=snapshot,
            )
    try:
        history = resolve_annual_history(
            selected.facts,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
            profile=profile,
            working_capital_inputs=working_capital_inputs,
        )
        metrics = derive_historical_metrics(history)
    except (PreparationError, AnnualHistoryError) as error:
        metrics = HistoricalMetricsV1(
            profile_id=profile.profile_id,
            profile_digest=profile.digest,
            quality_status=QualityStatus.ABSTAIN,
            issue_codes=(error.code,),
            missing_evidence=error.missing
            if isinstance(error, PreparationError)
            else (),
        )
        return _blocked_from_metrics(
            metrics,
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            facts=selected.facts,
            snapshot=snapshot,
        )
    if metrics.quality_status is QualityStatus.ABSTAIN:
        return _blocked_from_metrics(
            metrics,
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            facts=selected.facts,
            snapshot=snapshot,
        )
    try:
        forecast = compose_forecast_assumptions(history, metrics)
    except PreparationError as error:
        return _blocked_from_metrics(
            metrics.model_copy(
                update={
                    "quality_status": QualityStatus.ABSTAIN,
                    "issue_codes": (*metrics.issue_codes, error.code),
                    "missing_evidence": (*metrics.missing_evidence, *error.missing),
                }
            ),
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            facts=selected.facts,
            snapshot=snapshot,
        )
    latest_revenue = history.periods[-1].fact("revenue")
    assert latest_revenue is not None and isinstance(latest_revenue.value, Decimal)
    metric_by_name: dict[str, list[HistoricalMetricV1]] = {}
    for metric in metrics.metrics:
        metric_by_name.setdefault(metric.metric_id, []).append(metric)
    if market_policy is None:
        return _blocked_from_metrics(
            metrics.model_copy(
                update={
                    "issue_codes": (
                        *metrics.issue_codes,
                        "MARKET_POLICY_INPUTS_MISSING",
                    ),
                    "missing_evidence": (
                        *metrics.missing_evidence,
                        "approved_market_policy_inputs",
                    ),
                }
            ),
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            facts=selected.facts,
            snapshot=snapshot,
            status="requires_input",
        )
    try:
        assert market_policy.risk_free_rate is not None
        assert market_policy.beta is not None
        assert market_policy.equity_risk_premium is not None
        assert market_policy.pre_tax_cost_of_debt is not None
        assert market_policy.debt_weight is not None
        assert market_policy.equity_weight is not None
        assert market_policy.terminal_growth is not None
        tax_metrics = metric_by_name["normalized_tax_rate"]
        tax_rate = sum((item.value for item in tax_metrics), Decimal("0")) / Decimal(
            len(tax_metrics)
        )
        wacc = WaccAssumptionsV1.model_validate(
            {
                "risk_free_rate": market_policy.risk_free_rate,
                "beta": market_policy.beta,
                "equity_risk_premium": market_policy.equity_risk_premium,
                "pre_tax_cost_of_debt": market_policy.pre_tax_cost_of_debt,
                "tax_rate": tax_rate,
                "debt_weight": market_policy.debt_weight,
                "equity_weight": market_policy.equity_weight,
            }
        )
        terminal_growth = market_policy.terminal_growth
        if terminal_growth is None:
            raise ValueError("terminal growth is required")
        cost_of_equity = wacc.risk_free_rate + wacc.beta * wacc.equity_risk_premium
        weighted_average_cost = (
            cost_of_equity * wacc.equity_weight
            + wacc.pre_tax_cost_of_debt * (Decimal("1") - tax_rate) * wacc.debt_weight
        )
        if terminal_growth >= min(cost_of_equity, weighted_average_cost):
            raise PreparationError(
                "TERMINAL_GROWTH_NOT_BELOW_DISCOUNT_RATE",
                "terminal growth must be below the applicable discount rates",
            )
        if equity_dilution_evidence is None:
            raise PreparationError(
                "DILUTION_EVIDENCE_MISSING",
                "reviewed award inventory and valuation-date quote are required",
                missing=("equity_dilution_evidence",),
            )
        verify_dilution_fact_bindings(
            equity_dilution_evidence, snapshot=snapshot, released_facts=selected.facts
        )
        dilution = compute_treasury_stock_dilution(
            equity_dilution_evidence.inventory,
            equity_dilution_evidence.quote,
            equity_dilution_evidence.policy,
            valuation_timestamp=snapshot.valuation_timestamp,
        )
        capital = _capital_bridge(selected.facts, snapshot, dilution)
    except (PreparationError, TypeError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, (PreparationError, DilutionError))
            else "MARKET_POLICY_INPUTS_INVALID"
        )
        missing = error.missing if isinstance(error, PreparationError) else ()
        return _blocked_from_metrics(
            metrics.model_copy(
                update={
                    "quality_status": QualityStatus.ABSTAIN,
                    "issue_codes": (*metrics.issue_codes, code),
                    "missing_evidence": (*metrics.missing_evidence, *missing),
                }
            ),
            profile=profile,
            model_id=model_id,
            model_version=model_version,
            policy_id=policy_id,
            policy_version=policy_version,
            facts=selected.facts,
            snapshot=snapshot,
        )
    evidence = (
        _assumption_evidence(
            "assumptions.forecast.base_revenue",
            latest_revenue.value,
            "derived",
            "latest annual revenue",
            facts=(latest_revenue,),
            policy_version=policy_version,
            as_of=latest_revenue.available_at,
        ),
        _assumption_evidence(
            "assumptions.terminal_growth",
            terminal_growth,
            "approved_policy",
            "approved market/policy input",
            trace=market_policy.evidence["terminal_growth"],
            policy_version=market_policy.policy_version,
            as_of=(
                market_policy.evidence["terminal_growth"].as_of
                or snapshot.valuation_timestamp
            ),
        ),
    )
    assumptions = AssumptionsV1(
        forecast=forecast,
        wacc=wacc,
        terminal_growth=market_policy.terminal_growth,
        capital_bridge=capital,
        trace=TraceV1(
            expression="service-owned historical metrics and approved policy inputs",
            source_refs=tuple(
                item.output_digest for item in metrics.working_capital_assessments
            ),
            inputs=tuple(item.fact_id for item in selected.facts),
            description=(
                (
                    "automatic deterministic FCFF preparation with pinned "
                    "transition filing evidence"
                )
                if transition_evidence
                else "automatic deterministic FCFF preparation"
            ),
        ),
    )
    history_years = tuple(period.fiscal_year for period in history.periods)
    context = ValuationContextV1(
        valuation_timestamp=snapshot.valuation_timestamp,
        data_snapshot_id=snapshot.snapshot_id,
        fiscal_period_selector=FiscalPeriodSelectorV1(
            mode="explicit_periods",
            periods=tuple(FiscalPeriodV1(fiscal_year=year) for year in history_years),
        ),
        data_release_manifest_digest=data_release_manifest_digest,
        source_selection_policy=snapshot.policy_version,
        coverage_profile=profile.profile_id,
    )
    request = ValuationInputV1(
        contract_version="fundamental.v1",
        identity=snapshot.identity,
        valuation_context=context,
        historical_facts=tuple(sorted(item.fact_id for item in selected.facts)),
        assumptions=assumptions,
        uncertainty=UncertaintyV1(mode="none"),
        quality=QualityInputV1(
            status=metrics.quality_status,
            issue_codes=metrics.issue_codes,
            missing_evidence=metrics.missing_evidence,
        ),
        provenance=ProvenanceInputV1(
            snapshot_id=snapshot.snapshot_id,
            fact_ids=tuple(sorted(item.fact_id for item in selected.facts)),
            fiscal_period_selector=context.fiscal_period_selector,
            mapping_version=mapping_version,
            parser_version=snapshot.parser_version,
            taxonomy_version=snapshot.taxonomy_manifest_id or "sec-taxonomy-v1",
            policy_version=policy_version,
            preparation_version=FORECAST_COMPOSER_VERSION,
            equity_dilution_evidence_digest=equity_dilution_evidence.digest,
        ),
        model_id=model_id,
        model_version=model_version,
        policy_id=policy_id,
    ).with_digest()
    request = request.model_copy(
        update={
            "uncertainty": build_default_uncertainty(
                request,
                historical_metrics=metrics.metrics,
                policy_version=DEFAULT_UNCERTAINTY_POLICY_VERSION,
            )
        }
    ).with_digest()
    fact_by_id = {fact.fact_id: fact for fact in selected.facts}

    def metric_facts(metric_name: str) -> tuple[CanonicalFactV1, ...]:
        fact_ids = {
            fact_id
            for metric in metric_by_name.get(metric_name, ())
            for fact_id in metric.fact_ids
        }
        return tuple(fact_by_id[fact_id] for fact_id in sorted(fact_ids))

    def latest_fact_time(facts: Iterable[CanonicalFactV1]) -> datetime:
        fact_items = tuple(facts)
        return max(
            (fact.available_at for fact in fact_items),
            default=snapshot.valuation_timestamp,
        )

    growth_facts = metric_facts("revenue_growth")
    margin_facts = metric_facts("operating_margin")
    reinvestment_facts = metric_facts("reinvestment_rate")
    tax_facts = metric_facts("normalized_tax_rate")
    capital_fact_map = _capital_bridge_facts(selected.facts, snapshot=snapshot)
    share_facts = (
        capital_fact_map["common_shares_outstanding"],
        *equity_dilution_evidence.facts,
        capital_fact_map["other_share_classes"],
    )
    assumptions_evidence = (
        *evidence,
        *tuple(
            _assumption_evidence(
                f"assumptions.forecast.revenue_growth[{index}]",
                value,
                "derived",
                (
                    "mean(historical revenue_growth) * (forecast_periods - index) "
                    "/ forecast_periods"
                ),
                facts=growth_facts,
                policy_version=policy_version,
                as_of=latest_fact_time(growth_facts),
            )
            for index, value in enumerate(forecast.revenue_growth)
        ),
        *tuple(
            _assumption_evidence(
                f"assumptions.forecast.operating_margin[{index}]",
                forecast.operating_margin[index],
                "derived",
                "mean(last_three historical operating_margin)",
                facts=margin_facts,
                policy_version=policy_version,
                as_of=latest_fact_time(margin_facts),
            )
            for index in range(_FORECAST_PERIODS)
        ),
        *tuple(
            _assumption_evidence(
                f"assumptions.forecast.reinvestment_rate[{index}]",
                forecast.reinvestment_rate[index],
                "derived",
                "clamp(mean(historical reinvestment_rate), -1, 1)",
                facts=reinvestment_facts,
                policy_version=policy_version,
                as_of=latest_fact_time(reinvestment_facts),
            )
            for index in range(_FORECAST_PERIODS)
        ),
        _assumption_evidence(
            "assumptions.wacc.tax_rate",
            tax_rate,
            "derived",
            "mean(historical normalized_tax_rate)",
            facts=tax_facts,
            policy_version=policy_version,
            as_of=latest_fact_time(tax_facts),
        ),
        *tuple(
            _assumption_evidence(
                f"assumptions.wacc.{field}",
                getattr(market_policy, field),
                (
                    "approved_source"
                    if market_policy.evidence_methods.get(field) == "observed_source"
                    else "approved_policy"
                ),
                "released market policy input",
                trace=market_policy.evidence[field],
                policy_version=market_policy.policy_version,
                as_of=(
                    market_policy.evidence[field].as_of or snapshot.valuation_timestamp
                ),
            )
            for field in (
                "risk_free_rate",
                "beta",
                "equity_risk_premium",
                "pre_tax_cost_of_debt",
                "debt_weight",
                "equity_weight",
            )
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.cash",
            capital.cash,
            "derived",
            "cash_and_equivalents",
            facts=(capital_fact_map["cash_and_equivalents"],),
            policy_version=policy_version,
            as_of=latest_fact_time((capital_fact_map["cash_and_equivalents"],)),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.non_operating_assets",
            capital.non_operating_assets,
            "derived",
            "non_operating_assets (excluding cash and operating working capital)",
            facts=(capital_fact_map["non_operating_assets"],),
            policy_version=policy_version,
            as_of=latest_fact_time((capital_fact_map["non_operating_assets"],)),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.debt",
            capital.debt,
            "derived",
            (
                "current_interest_bearing_debt + long_term_interest_bearing_debt "
                "+ convertible_instruments"
            ),
            facts=(
                capital_fact_map["current_interest_bearing_debt"],
                capital_fact_map["long_term_interest_bearing_debt"],
                capital_fact_map["convertible_instruments"],
            ),
            policy_version=policy_version,
            as_of=latest_fact_time(
                (
                    capital_fact_map["current_interest_bearing_debt"],
                    capital_fact_map["long_term_interest_bearing_debt"],
                    capital_fact_map["convertible_instruments"],
                )
            ),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.lease_liabilities",
            capital.lease_liabilities,
            "derived",
            "current_finance_lease_liabilities + long_term_finance_lease_liabilities",
            facts=tuple(
                capital_fact_map[field]
                for field in (
                    "current_finance_lease_liabilities",
                    "long_term_finance_lease_liabilities",
                )
            ),
            policy_version=policy_version,
            as_of=latest_fact_time(
                tuple(
                    capital_fact_map[field]
                    for field in (
                        "current_finance_lease_liabilities",
                        "long_term_finance_lease_liabilities",
                    )
                )
            ),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.preferred_stock",
            capital.preferred_stock,
            "derived",
            "preferred_claims",
            facts=(capital_fact_map["preferred_claims"],),
            policy_version=policy_version,
            as_of=latest_fact_time((capital_fact_map["preferred_claims"],)),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.non_controlling_interest",
            capital.non_controlling_interest,
            "derived",
            "noncontrolling_interests",
            facts=(capital_fact_map["noncontrolling_interests"],),
            policy_version=policy_version,
            as_of=latest_fact_time((capital_fact_map["noncontrolling_interests"],)),
        ),
        _assumption_evidence(
            "assumptions.capital_bridge.diluted_shares",
            capital.diluted_shares,
            "derived",
            "common_shares_outstanding + sum(max(0, award_quantity - (exercise_proceeds + unrecognized_compensation) / valuation_date_quote)) + other_share_classes",
            facts=share_facts,
            trace=TraceV1(
                source_refs=tuple(
                    sorted(
                        {
                            equity_dilution_evidence.quote.content_hash,
                            *(fact.source.content_hash for fact in share_facts),
                        }
                    )
                )
            ),
            policy_version=equity_dilution_evidence.policy.policy_version,
            as_of=max(
                latest_fact_time(share_facts), equity_dilution_evidence.quote.as_of
            ),
        ),
    )
    digest = sha256_digest(
        {
            "input": request,
            "metrics": metrics,
            "evidence": assumptions_evidence,
            "profile_digest": profile.digest,
        }
    )
    return AutomaticValuationPreparationV1(
        status="prepared",
        model_id=model_id,
        model_version=model_version,
        profile_id=profile.profile_id,
        profile_digest=profile.digest,
        policy_id=policy_id,
        policy_version=policy_version,
        quality_status=metrics.quality_status,
        issue_codes=metrics.issue_codes,
        missing_evidence=metrics.missing_evidence,
        historical_metrics=metrics,
        assumptions_evidence=assumptions_evidence,
        input=request,
        preparation_digest=digest,
        equity_dilution=dilution,
    )


@using_valuation_context
def prepare_automatic_valuation(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    data_release_manifest_digest: str,
    market_policy: ApprovedMarketPolicyInputsV1 | None = None,
    mapping_version: str = "sec-canonical-mapping-v1",
    equity_dilution_evidence: EquityDilutionEvidenceV1 | None = None,
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...] = (),
) -> AutomaticValuationPreparationV1:
    """Compose exact or explicitly versioned composite inputs; retain all refusals."""

    inputs = canonical_working_capital_inputs(working_capital_inputs)
    result = _prepare_automatic_valuation(
        facts,
        snapshot=snapshot,
        model_id=model_id,
        model_version=model_version,
        policy_id=policy_id,
        policy_version=policy_version,
        data_release_manifest_digest=data_release_manifest_digest,
        market_policy=market_policy,
        mapping_version=mapping_version,
        equity_dilution_evidence=equity_dilution_evidence,
        working_capital_inputs=inputs,
    )
    if not inputs:
        return result
    metrics = result.historical_metrics.model_copy(
        update={"working_capital_inputs": inputs}
    )
    payload = {
        **result.model_dump(exclude={"preparation_digest"}),
        "historical_metrics": metrics,
    }
    return AutomaticValuationPreparationV1.model_validate(
        {**payload, "preparation_digest": sha256_digest(payload)}
    )


def _positive_observation_keys(fact: CanonicalFactV1) -> set[str]:
    evidence = fact.accounting_evidence
    if evidence is None:
        return {
            sha256_digest(
                {
                    "issuer": fact.issuer_id,
                    "concept": fact.concept,
                    "instant": fact.instant,
                    "start": fact.period_start,
                    "end": fact.period_end,
                    "unit": fact.unit.removeprefix("iso4217:"),
                    "dimensions": tuple(
                        sorted(
                            (dimension.name, dimension.member)
                            for dimension in fact.context.dimensions
                        )
                    ),
                }
            )
        }
    positive = {
        component.parsed_fact_digest
        for component in evidence.period_rule.components
        if component.sign == 1
    }
    return {
        sha256_digest(
            {
                "issuer": fact.issuer_id,
                "concept": observation.concept,
                "instant": observation.instant,
                "start": observation.period_start,
                "end": observation.instant or observation.period_end,
                "unit": (observation.unit or "").removeprefix("iso4217:"),
                "dimensions": tuple(sorted(observation.dimensions)),
            }
        )
        for observation in evidence.source_facts
        if observation.is_numeric and sha256_digest(observation) in positive
    }


def _require_disjoint_non_operating_assets(
    capital_facts: dict[str, CanonicalFactV1],
    facts: tuple[CanonicalFactV1, ...],
    snapshot: SourceSnapshotV1,
) -> None:
    asset = capital_facts["non_operating_assets"]
    cash = capital_facts["cash_and_equivalents"]
    if (
        asset.instant != cash.instant
        or asset.source.content_hash != cash.source.content_hash
        or asset.accession_number != cash.accession_number
        or asset.currency != snapshot.identity.currency
        or asset.unit not in {asset.currency, f"iso4217:{asset.currency}"}
        or asset.context.dimensions
        or asset.context.consolidation_scope != "consolidated"
        or not isinstance(asset.value, Decimal)
        or not asset.value.is_finite()
        or asset.value < 0
    ):
        raise PreparationError(
            "NON_OPERATING_ASSET_SCOPE_INVALID",
            "non-operating assets require a nonnegative consolidated currency amount at the cash balance date",
        )
    operating_fields = valuation_requirements_profile("fcff_dcf").annual_instant_fields
    used = _positive_observation_keys(cash)
    for fact in facts:
        if fact.normalized_field in operating_fields and fact.instant == asset.instant:
            used.update(_positive_observation_keys(fact))
    if _positive_observation_keys(asset) & used:
        raise PreparationError(
            "NON_OPERATING_ASSET_OVERLAP",
            "non-operating assets cannot reuse cash or operating working-capital observations",
        )


def _capital_bridge(
    facts: Iterable[CanonicalFactV1],
    snapshot: SourceSnapshotV1,
    dilution: TreasuryStockResultV1,
) -> CapitalBridgeAssumptionsV1:
    facts = tuple(facts)
    facts_by_field = _capital_bridge_facts(facts, snapshot=snapshot)
    _require_disjoint_non_operating_assets(facts_by_field, facts, snapshot)
    values = {
        name: fact.value
        for name, fact in facts_by_field.items()
        if isinstance(fact.value, Decimal)
    }
    if len(values) != len(facts_by_field):
        raise PreparationError(
            "METRIC_NON_NUMERIC_VALUE", "capital bridge facts must be numeric"
        )
    return CapitalBridgeAssumptionsV1(
        cash=values["cash_and_equivalents"],
        non_operating_assets=values["non_operating_assets"],
        debt=(
            values["current_interest_bearing_debt"]
            + values["long_term_interest_bearing_debt"]
            + values["convertible_instruments"]
        ),
        preferred_stock=values["preferred_claims"],
        lease_liabilities=(
            values["current_finance_lease_liabilities"]
            + values["long_term_finance_lease_liabilities"]
        ),
        non_controlling_interest=values["noncontrolling_interests"],
        diluted_shares=(
            values["common_shares_outstanding"]
            + dilution.incremental_shares
            + values["other_share_classes"]
        ),
    )


def _capital_bridge_facts(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1 | None = None,
) -> dict[str, CanonicalFactV1]:
    values: dict[str, CanonicalFactV1] = {}
    valuation_date = snapshot.valuation_timestamp.date() if snapshot else None
    for field in (
        "cash_and_equivalents",
        "non_operating_assets",
        "current_interest_bearing_debt",
        "long_term_interest_bearing_debt",
        "current_operating_lease_liabilities",
        "long_term_operating_lease_liabilities",
        "current_finance_lease_liabilities",
        "long_term_finance_lease_liabilities",
        "preferred_claims",
        "noncontrolling_interests",
        "convertible_instruments",
        "common_shares_outstanding",
        "other_share_classes",
    ):
        eligible = tuple(
            fact
            for fact in facts
            if valuation_date is None
            or fact.instant is None
            or fact.instant <= valuation_date
        )
        fact = _latest_fact(eligible, field)
        if fact is None:
            raise PreparationError(
                "CAPITAL_BRIDGE_FACTS_MISSING",
                f"capital bridge fact {field} is missing",
                missing=(field,),
            )
        values[field] = fact
    return values


def _blocked_from_metrics(
    metrics: HistoricalMetricsV1,
    *,
    profile: ValuationRequirementsProfileV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    facts: Iterable[CanonicalFactV1],
    snapshot: SourceSnapshotV1,
    status: Literal["requires_input", "abstained"] = "abstained",
) -> AutomaticValuationPreparationV1:
    missing = tuple(sorted(set(metrics.missing_evidence)))
    return _blocked_preparation(
        status=status,
        quality=metrics.quality_status,
        profile=profile,
        model_id=model_id,
        model_version=model_version,
        policy_id=policy_id,
        policy_version=policy_version,
        issues=metrics.issue_codes,
        missing=missing,
        facts=facts,
        snapshot=snapshot,
        metrics=metrics,
    )


def _blocked_preparation(
    *,
    status: Literal["requires_input", "abstained"],
    quality: QualityStatus,
    profile: ValuationRequirementsProfileV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    issues: Iterable[str],
    missing: Iterable[str],
    facts: Iterable[CanonicalFactV1],
    snapshot: SourceSnapshotV1,
    metrics: HistoricalMetricsV1 | None = None,
) -> AutomaticValuationPreparationV1:
    if metrics is None:
        metrics = HistoricalMetricsV1(
            profile_id=profile.profile_id,
            profile_digest=profile.digest,
            quality_status=quality,
            issue_codes=tuple(dict.fromkeys(issues)),
            missing_evidence=tuple(sorted(set(missing))),
        )
    payload = {
        "status": status,
        "model_id": model_id,
        "model_version": model_version,
        "profile_id": profile.profile_id,
        "profile_digest": profile.digest,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "quality_status": quality,
        "issue_codes": tuple(dict.fromkeys(issues)),
        "missing_evidence": tuple(sorted(set(missing))),
        "historical_metrics": metrics,
        "assumptions_evidence": (),
        "input": None,
    }
    digest_payload = {
        **payload,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_manifest_digest": snapshot.manifest_digest,
        "fact_ids": tuple(sorted(fact.fact_id for fact in facts)),
    }
    return AutomaticValuationPreparationV1.model_validate(
        {**payload, "preparation_digest": sha256_digest(digest_payload)}
    )


__all__ = [
    "ApprovedMarketPolicyInputsV1",
    "AssumptionEvidenceV1",
    "AutomaticValuationPreparationV1",
    "ForwardReferenceProvenanceV1",
    "HistoricalMetricV1",
    "HistoricalMetricsV1",
    "ManualProvenanceV1",
    "ManualValuationOverrideRequestV1",
    "PreparationError",
    "apply_manual_override",
    "derive_historical_metrics",
    "prepare_automatic_valuation",
]
