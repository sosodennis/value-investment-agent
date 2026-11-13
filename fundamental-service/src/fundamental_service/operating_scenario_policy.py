"""Research allocation policy and explicit nonoperands; no release authority."""

from typing import Annotated, Literal

from pydantic import Field

from .contracts import StrictModel
from .serialization import sha256_digest

SCENARIO_POLICY: Literal["nonnegative-parent-partitions-v1"] = (
    "nonnegative-parent-partitions-v1"
)
BASELINE_SCENARIO_POLICY = "baseline-unconsumed-capex-v2"
BASELINE_SOURCE_POLICY = "latest-complete-original-per-baseline-family-v2"
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


def scenario_policy_digest(policy_version: str = SCENARIO_POLICY) -> str:
    if policy_version == BASELINE_SCENARIO_POLICY:
        return sha256_digest(
            {
                "version": BASELINE_SCENARIO_POLICY,
                "allocation_policy": scenario_policy_digest(),
                "baseline_capex": "explicit unknown nonoperand only in earliest decision period",
                "consumed_capex": "every later period remains observed and allocated",
                "label_policy": "unchanged strict same-original conditional label",
                "baseline_source_policy": BASELINE_SOURCE_POLICY,
                "baseline_families": "latest complete core flows and latest complete working-capital stocks; same original within each family",
            }
        )
    if policy_version != SCENARIO_POLICY:
        raise ValueError("unsupported scenario input policy")
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


class UnconsumedBaselineCapexV1(StrictModel):
    """Unknown accounting amount whose baseline value is never an FCFF operand."""

    status: Literal["unknown_unconsumed"] = "unknown_unconsumed"
    role: Literal["capital_expenditure"] = "capital_expenditure"
    reason: Literal["baseline_not_consumed_by_fcff"] = "baseline_not_consumed_by_fcff"
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digests: tuple[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], ...] = (
        Field(min_length=1)
    )
    rationale: str = Field(min_length=40)
