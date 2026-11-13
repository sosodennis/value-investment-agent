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
from .operating_projection import resolve_operating_model
from .original_issuer import IssuerOperatingSourceV1
from .serialization import sha256_digest
from .valuation_preparation import FORECAST_COMPOSER_VERSION, HistoricalMetricsV1

from .operating_scenario_policy import (
    BASELINE_SCENARIO_POLICY,
    BASELINE_SOURCE_POLICY,
    CORE_FIELDS as CORE_FIELDS,
    PARENT_CONCEPTS as PARENT_CONCEPTS,
    SCENARIO_POLICY as SCENARIO_POLICY,
    UNRESOLVED_CLASSES as UNRESOLVED_CLASSES,
    UnconsumedBaselineCapexV1,
    scenario_policy_digest as scenario_policy_digest,
)


class ScenarioPeriodV1(StrictModel):
    fiscal_year: int = Field(ge=1900, le=2200)
    period_start: date
    period_end: date
    fact_ids: dict[str, str]
    unconsumed_capex: UnconsumedBaselineCapexV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def complete_period(self) -> "ScenarioPeriodV1":
        expected = {*CORE_FIELDS, *PARENT_CONCEPTS}
        if self.unconsumed_capex is not None:
            expected.remove("capital_expenditure")
        if set(self.fact_ids) != expected:
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


class ScenarioObservationSetV1(StrictModel):
    """Original observations and mappings shared by decision and label research."""

    source: IssuerOperatingSourceV1
    facts: tuple[CanonicalFactV1, ...] = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    mapping_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mappings: tuple[CanonicalMappingV1, ...] = Field(min_length=1)
    source_selection_policy: Literal[
        "latest-complete-original-per-period-v1",
        "latest-complete-original-per-baseline-family-v2",
    ] = "latest-complete-original-per-period-v1"

    @model_validator(mode="after")
    def mapping_manifest_is_pinned(self) -> "ScenarioObservationSetV1":
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
        return self


class OperatingScenarioRequestV1(ScenarioObservationSetV1):
    contract_version: Literal[
        "fundamental.operating-scenarios.v1", "fundamental.operating-scenarios.v2"
    ] = "fundamental.operating-scenarios.v1"
    evidence_status: Literal["unreviewed_source_scenario"] = (
        "unreviewed_source_scenario"
    )
    periods: tuple[ScenarioPeriodV1, ...] = Field(min_length=3, max_length=5)
    scenarios: tuple[OperatingScenarioV1, ...] = Field(min_length=1, max_length=1000)
    protocol_version: str = Field(min_length=1)
    policy_version: Literal[
        "nonnegative-parent-partitions-v1", "baseline-unconsumed-capex-v2"
    ] = SCENARIO_POLICY
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_versions: dict[InitialModelId, str]
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
        baseline_policy = self.policy_version == BASELINE_SCENARIO_POLICY
        if (
            self.contract_version == "fundamental.operating-scenarios.v2"
        ) != baseline_policy:
            raise ValueError(
                "scenario contract and input policy must be versioned together"
            )
        if (self.source_selection_policy == BASELINE_SOURCE_POLICY) != baseline_policy:
            raise ValueError(
                "baseline family source selection requires the explicit v2 policy"
            )
        if any(
            period.unconsumed_capex is not None and (not baseline_policy or index != 0)
            for index, period in enumerate(self.periods)
        ):
            raise ValueError(
                "unknown capex is only admissible in the v2 decision baseline"
            )
        capex_years = {
            p.fiscal_year for p in self.periods if p.unconsumed_capex is None
        }
        if any(
            set(item.continuing_capex_fractions) != capex_years
            for item in self.scenarios
        ):
            raise ValueError(
                "every scenario must explicitly allocate every capex period"
            )
        if self.policy_digest != scenario_policy_digest(self.policy_version):
            raise ValueError(
                "scenario policy digest differs from the executable policy"
            )
        if set(self.model_versions) != {"fcff_dcf", "transition_fcff_dcf"}:
            raise ValueError("both formal model versions must be pinned")
        for model_id, version in self.model_versions.items():
            resolve_operating_model(model_id, version)
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
    capex: ParentPartitionV1 | UnconsumedBaselineCapexV1
    operating_working_capital: Decimal
    assumption_digest: str


class OperatingScenarioResultV1(StrictModel):
    scenario_id: str
    model_id: InitialModelId
    model_version: str
    model_spec_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    contract_version: Literal[
        "fundamental.operating-scenario-replay.v2",
        "fundamental.operating-scenario-replay.v3",
    ] = "fundamental.operating-scenario-replay.v2"
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
