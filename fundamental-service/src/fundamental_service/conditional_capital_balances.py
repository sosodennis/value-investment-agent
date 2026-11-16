"""Explicit what-if balances; these operands never become observed source facts."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CapitalBalanceRole = Literal[
    "non_operating_assets",
    "current_interest_bearing_debt",
    "noncontrolling_interests",
]
CAPITAL_BALANCE_ROLES: tuple[CapitalBalanceRole, ...] = (
    "current_interest_bearing_debt",
    "non_operating_assets",
    "noncontrolling_interests",
)
CAPITAL_BALANCE_HYPOTHESES: Literal["conditional-capital-balance-hypotheses-v1"] = (
    "conditional-capital-balance-hypotheses-v1"
)
NonnegativeAmount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class _BalanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CapitalBalanceScenarioV1(_BalanceModel):
    name: Literal["base", "downside", "upside"]
    values: dict[CapitalBalanceRole, NonnegativeAmount] = Field(min_length=1)
    rationale: dict[CapitalBalanceRole, str]

    @model_validator(mode="after")
    def every_operand_is_explained(self) -> "CapitalBalanceScenarioV1":
        if set(self.rationale) != set(self.values) or any(
            len(text.strip()) < 40 for text in self.rationale.values()
        ):
            raise ValueError("every hypothetical balance requires its own rationale")
        return self


class CapitalBalanceHypothesesV1(_BalanceModel):
    """Balances use the bridge role's scope, excluding other bridge operands.

    Non-operating assets exclude cash and operating assets; current debt excludes
    noncurrent debt and additional convertible exposures declared elsewhere.
    These are complete hypothetical role operands, never measured subtotals.
    """

    protocol: Literal["conditional-capital-balance-hypotheses-v1"] = (
        CAPITAL_BALANCE_HYPOTHESES
    )
    interpretation: Literal["conditional_hypotheses_not_estimates_or_bounds"] = (
        "conditional_hypotheses_not_estimates_or_bounds"
    )
    unknown_fields: tuple[CapitalBalanceRole, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    scenarios: tuple[CapitalBalanceScenarioV1, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def scope_and_sensitivity_are_explicit(self) -> "CapitalBalanceHypothesesV1":
        if self.unknown_fields != tuple(sorted(set(self.unknown_fields))):
            raise ValueError("hypothetical balance roles must be distinct and ordered")
        if tuple(row.name for row in self.scenarios) != ("base", "downside", "upside"):
            raise ValueError("balance hypotheses require ordered base/downside/upside")
        if any(len(text.strip()) < 40 for text in self.limitations):
            raise ValueError("balance hypotheses require explicit limitations")
        for row in self.scenarios:
            if set(row.values) != set(self.unknown_fields):
                raise ValueError(
                    "every scenario must cover exactly the unknown balances"
                )
        for role in self.unknown_fields:
            if len({row.values[role] for row in self.scenarios}) < 2:
                raise ValueError(f"hypothetical balance requires sensitivity: {role}")
        return self
