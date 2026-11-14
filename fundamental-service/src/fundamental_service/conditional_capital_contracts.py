"""Immutable source-bound conditional capital input and assessment contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import CanonicalFactV1, CapitalBridgeAssumptionsV1
from .serialization import sha256_digest

CONDITIONAL_CAPITAL_POLICY: Literal["conditional-capital-hypotheses-v1"] = (
    "conditional-capital-hypotheses-v1"
)
OBSERVED_CAPITAL_FIELDS = (
    "cash_and_equivalents",
    "non_operating_assets",
    "current_interest_bearing_debt",
    "long_term_interest_bearing_debt",
    "current_operating_lease_liabilities",
    "long_term_operating_lease_liabilities",
    "current_finance_lease_liabilities",
    "long_term_finance_lease_liabilities",
    "noncontrolling_interests",
    "common_shares_outstanding",
)
UNRESOLVED_CAPITAL_FIELDS = (
    "preferred_claims",
    "convertible_instruments",
    "other_share_classes",
)
CAPITAL_UNKNOWNS = (
    *UNRESOLVED_CAPITAL_FIELDS,
    "complete_award_inventory",
    "per_strike_inventory",
    "compensation_allocation",
)


class _CapitalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CapitalObservationRefV1(_CapitalModel):
    fact_id: str = Field(min_length=1)
    fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class HypotheticalConvertibleDebtV1(_CapitalModel):
    treatment: Literal["debt"] = "debt"
    additional_debt: Decimal = Field(ge=0, allow_inf_nan=False)


class HypotheticalConversionV1(_CapitalModel):
    treatment: Literal["if_converted"] = "if_converted"
    additional_common_equivalent_shares: Decimal = Field(ge=0, allow_inf_nan=False)


def _convertible_exposure(
    value: HypotheticalConvertibleDebtV1 | HypotheticalConversionV1,
) -> tuple[Decimal, Decimal]:
    if isinstance(value, HypotheticalConvertibleDebtV1):
        return value.additional_debt, Decimal(0)
    return Decimal(0), value.additional_common_equivalent_shares


class CapitalHypothesisV1(_CapitalModel):
    name: Literal["base", "downside", "upside"]
    preferred_claims: Decimal = Field(ge=0, allow_inf_nan=False)
    convertible: Annotated[
        HypotheticalConvertibleDebtV1 | HypotheticalConversionV1,
        Field(discriminator="treatment"),
    ]
    other_common_equivalent_shares: Decimal = Field(ge=0, allow_inf_nan=False)
    incremental_award_shares: Decimal = Field(ge=0, allow_inf_nan=False)
    rationale: dict[
        Literal[
            "preferred_claims",
            "convertible_instruments",
            "other_share_classes",
            "award_dilution",
        ],
        str,
    ]

    @model_validator(mode="after")
    def every_hypothesis_is_explained(self) -> CapitalHypothesisV1:
        if set(self.rationale) != {*UNRESOLVED_CAPITAL_FIELDS, "award_dilution"} or any(
            len(text.strip()) < 40 for text in self.rationale.values()
        ):
            raise ValueError(
                "every unresolved capital hypothesis requires an explicit rationale"
            )
        return self


class ConditionalCapitalPolicyV1(_CapitalModel):
    protocol: Literal["conditional-capital-hypotheses-v1"] = CONDITIONAL_CAPITAL_POLICY
    interpretation: Literal["conditional_hypotheses_not_estimates_or_bounds"] = (
        "conditional_hypotheses_not_estimates_or_bounds"
    )
    complete_capital_claims: Literal[False] = False
    complete_award_inventory: Literal[False] = False
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    security_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valuation_timestamp: datetime
    period_end: date
    max_quote_age_seconds: int = Field(gt=0)
    observations: dict[str, CapitalObservationRefV1]
    supporting_observations: tuple[CapitalObservationRefV1, ...] = Field(min_length=1)
    unknowns: tuple[str, ...]
    limitations: tuple[str, ...] = Field(min_length=1)
    scenarios: tuple[CapitalHypothesisV1, ...] = Field(min_length=3, max_length=3)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation timestamp requires a timezone")
        return value

    @field_validator("supporting_observations")
    @classmethod
    def canonical_supporting_observations(
        cls, values: tuple[CapitalObservationRefV1, ...]
    ) -> tuple[CapitalObservationRefV1, ...]:
        return tuple(sorted(values, key=lambda item: item.fact_id))

    @field_validator("scenarios")
    @classmethod
    def canonical_scenarios(
        cls, values: tuple[CapitalHypothesisV1, ...]
    ) -> tuple[CapitalHypothesisV1, ...]:
        order = {"base": 0, "downside": 1, "upside": 2}
        return tuple(sorted(values, key=lambda item: order[item.name]))

    @model_validator(mode="after")
    def policy_keeps_unknowns_and_sensitivity(self) -> ConditionalCapitalPolicyV1:
        if self.model_version != f"{self.model_id}-v2":
            raise ValueError(
                "conditional capital requires the supported FCFF model version"
            )
        if self.period_end > self.valuation_timestamp.date():
            raise ValueError("capital observations cannot have a future balance date")
        if set(self.observations) != set(OBSERVED_CAPITAL_FIELDS):
            raise ValueError("conditional capital requires every observed capital role")
        references = (*self.observations.values(), *self.supporting_observations)
        if len({item.fact_id for item in references}) != len(references):
            raise ValueError("capital observations cannot repeat a fact")
        if len(self.unknowns) != len(CAPITAL_UNKNOWNS) or set(self.unknowns) != set(
            CAPITAL_UNKNOWNS
        ):
            raise ValueError(
                "conditional capital must retain every unresolved claim and award role"
            )
        if any(len(text.strip()) < 40 for text in self.limitations):
            raise ValueError("conditional capital requires explicit limitations")
        if {item.name for item in self.scenarios} != {"base", "downside", "upside"}:
            raise ValueError(
                "capital scenarios must be distinct base, downside and upside"
            )
        sensitivity: dict[str, set[Decimal] | set[tuple[Decimal, Decimal]]] = {
            "preferred_claims": {item.preferred_claims for item in self.scenarios},
            "convertible": {
                _convertible_exposure(item.convertible) for item in self.scenarios
            },
            "other_common_equivalent_shares": {
                item.other_common_equivalent_shares for item in self.scenarios
            },
            "incremental_award_shares": {
                item.incremental_award_shares for item in self.scenarios
            },
        }
        for field, values in sensitivity.items():
            if len(values) < 2:
                raise ValueError(
                    f"unresolved capital role requires scenario sensitivity: {field}"
                )
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class ConditionalCapitalScenarioV1(_CapitalModel):
    hypothesis: CapitalHypothesisV1
    bridge: CapitalBridgeAssumptionsV1


class ConditionalCapitalAssessmentV1(_CapitalModel):
    policy: ConditionalCapitalPolicyV1
    status: Literal["provisional_conditional_hypotheses"] = (
        "provisional_conditional_hypotheses"
    )
    source_facts: tuple[CanonicalFactV1, ...]
    scenarios: tuple[ConditionalCapitalScenarioV1, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def output_digest(self) -> str:
        return sha256_digest(self)
