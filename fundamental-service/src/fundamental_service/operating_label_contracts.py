"""Conditional outcomes and paired errors, without exact-label authority."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .contracts import InitialModelId, StrictModel
from .numerical_policy import VALUATION_NUMERICAL_POLICY
from .operating_scenario_contracts import (
    OperatingScenarioRequestV1,
    OperatingScenarioV1,
    ScenarioObservationSetV1,
    ScenarioPeriodInputsV1,
    ScenarioPeriodV1,
    UNRESOLVED_CLASSES,
    scenario_policy_digest,
)
from .serialization import sha256_digest
from .valuation_preparation import FORECAST_COMPOSER_VERSION, HistoricalMetricsV1

LABEL_POLICY: Literal["same-original-conditional-realized-fcff-v1"] = (
    "same-original-conditional-realized-fcff-v1"
)
COMPARISON_POLICY: Literal["paired-constant-wc-fractions-first-year-v1"] = (
    "paired-constant-wc-fractions-first-year-v1"
)


def operating_label_policy_digest() -> str:
    return sha256_digest(
        {
            "version": LABEL_POLICY,
            "selection": "first subsequent original annual filing in the pinned inventory; never skip a missing label",
            "basis": "prior and target periods from that same original, separate from origin facts",
            "allocation_policy": scenario_policy_digest(),
            "realization": "derive_historical_metrics.realized_fcff",
            "comparison": COMPARISON_POLICY,
            "pairing": "same asset and liability operating fractions; all explicit label capex assumptions",
            "signed_error": "forecast - conditional_realized",
            "normalized_error": "signed_error / origin_base_revenue",
            "claims": "sampled conditional comparisons only; no exact ground truth, CI or threshold",
        }
    )


class OriginalAnnualTargetV1(StrictModel):
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    available_at: datetime
    period_end: date
    form: str
    is_amendment: bool

    @model_validator(mode="after")
    def aware_publication(self) -> "OriginalAnnualTargetV1":
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("filing inventory requires timezone-aware availability")
        return self


class ConditionalLabelRequestV1(ScenarioObservationSetV1):
    """Label-only observations: these never enter the forecast request."""

    periods: tuple[ScenarioPeriodV1, ...] = Field(min_length=2, max_length=2)
    scenarios: tuple[OperatingScenarioV1, ...] = Field(min_length=1, max_length=1000)
    scope_assumption_evidence_digests: tuple[str, ...] = Field(min_length=1)
    unresolved_classes: tuple[str, ...]

    @model_validator(mode="after")
    def complete_label_grid(self) -> "ConditionalLabelRequestV1":
        if self.source_selection_policy != "latest-complete-original-per-period-v1":
            raise ValueError(
                "labels require the unchanged complete-original source policy"
            )
        if any(period.unconsumed_capex is not None for period in self.periods):
            raise ValueError(
                "label periods require observed capex; baseline exemption is decision-only"
            )
        years = tuple(period.fiscal_year for period in self.periods)
        if years[1] != years[0] + 1:
            raise ValueError(
                "conditional labels require consecutive prior/target periods"
            )
        if tuple(item.scenario_id for item in self.scenarios) != tuple(
            sorted({item.scenario_id for item in self.scenarios})
        ):
            raise ValueError("label scenarios must have ordered unique identities")
        if any(
            set(item.continuing_capex_fractions) != set(years)
            for item in self.scenarios
        ):
            raise ValueError(
                "label capex allocations must explicitly cover both periods"
            )
        if self.unresolved_classes != UNRESOLVED_CLASSES:
            raise ValueError("unknown label classifications cannot be removed")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.scope_assumption_evidence_digests
        ):
            raise ValueError("label assumptions require canonical evidence digests")
        return self


class OperatingComparisonRequestV1(StrictModel):
    contract_version: Literal[
        "fundamental.operating-comparison.v1", "fundamental.operating-comparison.v2"
    ] = "fundamental.operating-comparison.v1"
    decision: OperatingScenarioRequestV1
    decision_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: ConditionalLabelRequestV1
    filing_inventory: tuple[OriginalAnnualTargetV1, ...] = Field(min_length=1)
    filing_inventory_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory_evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1)
    policy_version: Literal["same-original-conditional-realized-fcff-v1"] = LABEL_POLICY
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    pairing_policy: Literal["paired-constant-wc-fractions-first-year-v1"] = (
        COMPARISON_POLICY
    )

    @model_validator(mode="after")
    def pinned_comparison(self) -> "OperatingComparisonRequestV1":
        if (self.contract_version == "fundamental.operating-comparison.v2") != (
            self.decision.contract_version == "fundamental.operating-scenarios.v2"
        ):
            raise ValueError("comparison and decision contract versions must match")
        if self.decision_input_digest != sha256_digest(self.decision):
            raise ValueError("decision input must remain frozen and separate")
        if self.filing_inventory_digest != sha256_digest(self.filing_inventory):
            raise ValueError("filing inventory digest mismatch")
        keys = tuple(
            (item.available_at, item.accession_number) for item in self.filing_inventory
        )
        if keys != tuple(sorted(set(keys))) or len(
            {item.accession_number for item in self.filing_inventory}
        ) != len(keys):
            raise ValueError("filing inventory must be chronological and unique")
        if self.policy_digest != operating_label_policy_digest():
            raise ValueError("label policy differs from its executable version")
        return self


class ConditionalOperatingLabelV1(StrictModel):
    scenario_id: str
    status: Literal["provisional_conditional_label", "abstained"]
    target_period_start: date
    target_period_end: date
    accession_number: str
    available_at: datetime
    period_inputs: tuple[ScenarioPeriodInputsV1, ...]
    historical_metrics: HistoricalMetricsV1 | None
    realized_fcff: Decimal | None
    issue_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    supported_history_threshold: None = None


class OperatingScenarioErrorV1(StrictModel):
    forecast_scenario_id: str
    label_scenario_id: str
    model_id: InitialModelId
    status: Literal["provisional_conditional_comparison", "abstained"]
    forecast_fcff: Decimal | None
    conditional_realized_fcff: Decimal | None
    signed_error: Decimal | None
    absolute_error: Decimal | None
    origin_base_revenue: Decimal | None
    normalized_signed_error: Decimal | None
    issue_codes: tuple[str, ...]


class OperatingScenarioComparisonV1(StrictModel):
    contract_version: Literal[
        "fundamental.operating-comparison-replay.v1",
        "fundamental.operating-comparison-replay.v2",
    ] = "fundamental.operating-comparison-replay.v1"
    evidence_status: Literal["unreviewed_conditional_scenario_comparison"] = (
        "unreviewed_conditional_scenario_comparison"
    )
    bounds_claim: Literal["sampled_conditional_comparisons_only"] = (
        "sampled_conditional_comparisons_only"
    )
    input_digest: str
    output_digest: str
    decision_input_digest: str
    forecast_output_digest: str
    label_input_digest: str
    composer_version: str = FORECAST_COMPOSER_VERSION
    numerical_policy_version: str = VALUATION_NUMERICAL_POLICY
    label_policy_digest: str
    retained_label_fact_ids: tuple[str, ...]
    labels: tuple[ConditionalOperatingLabelV1, ...]
    comparisons: tuple[OperatingScenarioErrorV1, ...]
    independent_issuer_count: int = 1
    complete_exact_study_cases: Literal[0] = 0
    supported_history_threshold: None = None
