"""Versioned research inputs and results; these grant no release authority."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .contracts import (
    CalculationNodeV1,
    CanonicalFactV1,
    ForecastAssumptionsV1,
    InitialModelId,
    StrictModel,
)
from .facts import CanonicalMappingV1
from .numerical_policy import VALUATION_NUMERICAL_POLICY, using_valuation_context
from .original_issuer import IssuerOperatingSourceV1
from .serialization import sha256_digest
from .valuation_preparation import FORECAST_COMPOSER_VERSION, HistoricalMetricsV1

SCENARIO_POLICY: Literal["nonnegative-parent-partitions-v1"] = (
    "nonnegative-parent-partitions-v1"
)
CORE_FIELDS = (
    "revenue",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
    "depreciation_and_amortization",
)
PARENT_CONCEPTS = {
    "current_assets": "us-gaap:AssetsCurrent",
    "current_liabilities": "us-gaap:LiabilitiesCurrent",
    "cash_and_equivalents": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    "capital_expenditure": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
}
UNRESOLVED_CLASSES = (
    "short_term_investments",
    "current_interest_bearing_debt",
    "current_operating_lease_liabilities",
    "current_finance_lease_liabilities",
    "other_non_operating_current_assets_and_liabilities",
)


def scenario_policy_digest() -> str:
    return sha256_digest(
        {
            "version": SCENARIO_POLICY,
            "core_fields": CORE_FIELDS,
            "parent_concepts": PARENT_CONCEPTS,
            "unresolved_classes": UNRESOLVED_CLASSES,
            "assumptions": (
                "gross capex is a nonnegative sum of disjoint continuing and other cash payments",
                "current assets less reported cash partitions jointly into operating and excluded balances",
                "current liabilities partition jointly into operating and excluded balances",
                "no missing investment, debt, lease or other classification is known to be zero",
            ),
            "bounds_claim": "sampled scenarios only; no global bounds or confidence interval",
        }
    )


class ScenarioPeriodV1(StrictModel):
    fiscal_year: int = Field(ge=1900, le=2200)
    period_start: date
    period_end: date
    fact_ids: dict[str, str]

    @model_validator(mode="after")
    def complete_period(self) -> "ScenarioPeriodV1":
        if set(self.fact_ids) != {*CORE_FIELDS, *PARENT_CONCEPTS}:
            raise ValueError(
                "scenario period requires every core and parent observation"
            )
        if len(set(self.fact_ids.values())) != len(self.fact_ids):
            raise ValueError("one observation cannot fill multiple accounting roles")
        if self.period_end.year != self.fiscal_year or not (
            300 <= (self.period_end - self.period_start).days <= 380
        ):
            raise ValueError("scenario period must be an aligned annual period")
        return self


class OperatingScenarioV1(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    operating_asset_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    operating_liability_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    continuing_capex_fractions: dict[int, Decimal]
    rationale: str = Field(min_length=20)

    @model_validator(mode="after")
    def finite_capex_allocations(self) -> "OperatingScenarioV1":
        if not self.continuing_capex_fractions or any(
            not value.is_finite() or not 0 <= value <= 1
            for value in self.continuing_capex_fractions.values()
        ):
            raise ValueError(
                "each capex allocation requires an explicit finite fraction"
            )
        return self


class OperatingScenarioRequestV1(StrictModel):
    contract_version: Literal["fundamental.operating-scenarios.v1"] = (
        "fundamental.operating-scenarios.v1"
    )
    evidence_status: Literal["unreviewed_source_scenario"] = (
        "unreviewed_source_scenario"
    )
    source: IssuerOperatingSourceV1
    facts: tuple[CanonicalFactV1, ...] = Field(min_length=1)
    periods: tuple[ScenarioPeriodV1, ...] = Field(min_length=3, max_length=5)
    scenarios: tuple[OperatingScenarioV1, ...] = Field(min_length=1, max_length=1000)
    mapping_version: str = Field(min_length=1)
    mapping_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mappings: tuple[CanonicalMappingV1, ...] = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    policy_version: Literal["nonnegative-parent-partitions-v1"] = SCENARIO_POLICY
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_versions: dict[InitialModelId, str]
    source_selection_policy: Literal["latest-complete-original-per-period-v1"] = (
        "latest-complete-original-per-period-v1"
    )
    scope_assumption_evidence_digests: tuple[str, ...] = Field(min_length=1)
    unresolved_classes: tuple[str, ...]

    @model_validator(mode="after")
    def pinned_research(self) -> "OperatingScenarioRequestV1":
        years = tuple(period.fiscal_year for period in self.periods)
        if years != tuple(range(years[0], years[0] + len(years))):
            raise ValueError("scenario periods must be consecutive and chronological")
        if (
            tuple(sorted(self.scenarios, key=lambda item: item.scenario_id))
            != self.scenarios
        ):
            raise ValueError(
                "scenario grid must be ordered by stable scenario identity"
            )
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario identities must be unique")
        if any(
            set(item.continuing_capex_fractions) != set(years)
            for item in self.scenarios
        ):
            raise ValueError(
                "every scenario must explicitly allocate every capex period"
            )
        if self.policy_digest != scenario_policy_digest():
            raise ValueError(
                "scenario policy digest differs from the executable policy"
            )
        if (
            tuple(mapping.decision_id for mapping in self.mappings)
            != tuple(sorted({mapping.decision_id for mapping in self.mappings}))
            or any(
                mapping.mapping_version != self.mapping_version
                for mapping in self.mappings
            )
            or self.mapping_manifest_digest != sha256_digest(self.mappings)
        ):
            raise ValueError(
                "mapping manifest must pin ordered unique mappings and their version"
            )
        if set(self.model_versions) != {"fcff_dcf", "transition_fcff_dcf"} or any(
            not version for version in self.model_versions.values()
        ):
            raise ValueError("both formal model versions must be pinned")
        if self.unresolved_classes != UNRESOLVED_CLASSES:
            raise ValueError("unknown classification categories cannot be dropped")
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in self.scope_assumption_evidence_digests
        ):
            raise ValueError("scope assumptions require canonical evidence digests")
        return self


class ParentPartitionV1(StrictModel):
    parent_fact_id: str
    parent_value: Decimal
    known_exclusion_fact_ids: tuple[str, ...]
    known_excluded: Decimal
    operating: Decimal
    unresolved_excluded: Decimal

    @model_validator(mode="after")
    @using_valuation_context
    def conserved_parent(self) -> "ParentPartitionV1":
        if (
            min(
                self.parent_value,
                self.known_excluded,
                self.operating,
                self.unresolved_excluded,
            )
            < 0
        ):
            raise ValueError("nonnegative allocation assumptions are infeasible")
        if (
            self.known_excluded + self.operating + self.unresolved_excluded
            != self.parent_value
        ):
            raise ValueError("joint allocations must conserve their gross parent")
        return self


class ScenarioPeriodInputsV1(StrictModel):
    fiscal_year: int
    assets: ParentPartitionV1
    liabilities: ParentPartitionV1
    capex: ParentPartitionV1
    operating_working_capital: Decimal
    assumption_digest: str


class OperatingScenarioResultV1(StrictModel):
    scenario_id: str
    model_id: InitialModelId
    model_version: str
    status: Literal["provisional_scenario", "abstained"]
    issue_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    period_inputs: tuple[ScenarioPeriodInputsV1, ...]
    historical_metrics: HistoricalMetricsV1 | None
    forecast: ForecastAssumptionsV1 | None
    tax_rate: Decimal | None
    nodes: tuple[CalculationNodeV1, ...]
    supported_history_threshold: None = None


class OperatingScenarioReplayV1(StrictModel):
    contract_version: Literal["fundamental.operating-scenario-replay.v1"] = (
        "fundamental.operating-scenario-replay.v1"
    )
    evidence_status: Literal["unreviewed_source_scenario"] = (
        "unreviewed_source_scenario"
    )
    bounds_claim: Literal["sampled_scenarios_only"] = "sampled_scenarios_only"
    composer_version: str = FORECAST_COMPOSER_VERSION
    numerical_policy_version: str = VALUATION_NUMERICAL_POLICY
    input_digest: str
    output_digest: str
    retained_fact_ids: tuple[str, ...]
    results: tuple[OperatingScenarioResultV1, ...]
    supported_history_threshold: None = None
