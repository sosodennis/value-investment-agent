"""Source-bound forward assumptions; no claim of observed reinvestment."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import CanonicalFactV1
from .serialization import sha256_digest

CONDITIONAL_REINVESTMENT_POLICY: Literal["conditional-forward-reinvestment-v1"] = (
    "conditional-forward-reinvestment-v1"
)
REINVESTMENT_CORE_FIELDS = (
    "revenue",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
)
REINVESTMENT_UNKNOWNS = (
    "historical_capital_expenditure",
    "historical_depreciation_and_amortization",
    "historical_operating_working_capital",
    "historical_reinvestment_rate",
)


class _ReinvestmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ReinvestmentHypothesisV1(_ReinvestmentModel):
    name: Literal["base", "downside", "upside"]
    reinvestment_rate: Decimal = Field(ge=-1, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=40)

    @field_validator("rationale")
    @classmethod
    def rationale_has_content(cls, value: str) -> str:
        if len(value.strip()) < 40:
            raise ValueError("a reinvestment assumption requires an explicit rationale")
        return value


class ConditionalReinvestmentRecipeV1(_ReinvestmentModel):
    """Deployment assumptions awaiting exact original-derived history bindings."""

    protocol: Literal["conditional-reinvestment-recipe-v1"] = (
        "conditional-reinvestment-recipe-v1"
    )
    interpretation: Literal["conditional_hypotheses_not_estimates_or_bounds"] = (
        "conditional_hypotheses_not_estimates_or_bounds"
    )
    historical_reinvestment_observed: Literal[False] = False
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    assumption_document_uri: str = Field(min_length=1)
    assumption_document_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitations: tuple[str, ...] = Field(min_length=1)
    scenarios: tuple[ReinvestmentHypothesisV1, ...] = Field(min_length=3, max_length=3)

    @field_validator("scenarios")
    @classmethod
    def canonical_scenarios(
        cls, values: tuple[ReinvestmentHypothesisV1, ...]
    ) -> tuple[ReinvestmentHypothesisV1, ...]:
        order = {"base": 0, "downside": 1, "upside": 2}
        return tuple(sorted(values, key=lambda item: order[item.name]))

    @model_validator(mode="after")
    def explicit_supported_assumptions(self) -> ConditionalReinvestmentRecipeV1:
        if self.model_version not in {f"{self.model_id}-v2", f"{self.model_id}-v3"}:
            raise ValueError("forward hypotheses require the supported FCFF model")
        if any(len(text.strip()) < 40 for text in self.limitations):
            raise ValueError("forward hypotheses require explicit limitations")
        if {item.name for item in self.scenarios} != {"base", "downside", "upside"}:
            raise ValueError("forward hypotheses require three distinct scenarios")
        if len({item.reinvestment_rate for item in self.scenarios}) != 3:
            raise ValueError("forward hypotheses require distinct sensitivity rates")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class ReinvestmentObservationRefV1(_ReinvestmentModel):
    fact_id: str = Field(min_length=1)
    fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConditionalReinvestmentPolicyV1(_ReinvestmentModel):
    protocol: Literal["conditional-forward-reinvestment-v1"] = (
        CONDITIONAL_REINVESTMENT_POLICY
    )
    recipe: ConditionalReinvestmentRecipeV1
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    security_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valuation_timestamp: datetime
    observations: tuple[ReinvestmentObservationRefV1, ...] = Field(min_length=12)
    unknowns: tuple[str, ...] = REINVESTMENT_UNKNOWNS

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation timestamp requires a timezone")
        return value

    @field_validator("observations")
    @classmethod
    def canonical_observations(
        cls, values: tuple[ReinvestmentObservationRefV1, ...]
    ) -> tuple[ReinvestmentObservationRefV1, ...]:
        if len({item.fact_id for item in values}) != len(values):
            raise ValueError("forward policy observations cannot repeat a fact")
        return tuple(sorted(values, key=lambda item: item.fact_id))

    @model_validator(mode="after")
    def retains_unknown_history(self) -> ConditionalReinvestmentPolicyV1:
        if self.unknowns != REINVESTMENT_UNKNOWNS:
            raise ValueError("unknown historical reinvestment must remain explicit")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class ConditionalReinvestmentAssessmentV1(_ReinvestmentModel):
    policy: ConditionalReinvestmentPolicyV1
    status: Literal["provisional_conditional_hypotheses"] = (
        "provisional_conditional_hypotheses"
    )
    source_facts: tuple[CanonicalFactV1, ...]
    fiscal_years: tuple[int, ...]
    supported_history_threshold: Literal[None] = None
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def output_digest(self) -> str:
        return sha256_digest(self)
