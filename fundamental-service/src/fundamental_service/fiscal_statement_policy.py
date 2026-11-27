from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from .contracts import StrictModel
from .serialization import sha256_digest
from .statement_contracts import StatementRowId
from .statement_profiles import statement_row_definitions

Aggregation = Literal["additive_flow", "instant", "cash_opening", "cash_closing"]
FISCAL_STATEMENT_POLICY_ID = "us-gaap-nonfinancial-quarter-ttm-v1"


class FiscalRowPolicyV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    row_id: StatementRowId
    statement: Literal["income_statement", "balance_sheet", "cash_flow"]
    label: str
    aggregation: Aggregation


class FiscalUnsupportedRowFamilyV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    family: Literal[
        "eps_and_per_share", "weighted_average_shares", "ratios_and_margins"
    ]
    reason: str


class FiscalStatementPolicyV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    policy_id: Literal["us-gaap-nonfinancial-quarter-ttm-v1"] = (
        "us-gaap-nonfinancial-quarter-ttm-v1"
    )
    selection: Literal["latest-available-exact-period-and-row-v1"] = (
        "latest-available-exact-period-and-row-v1"
    )
    precision: Literal["reported-decimals-signed-intervals-v1"] = (
        "reported-decimals-signed-intervals-v1"
    )
    comparability: Literal["source-bound-observation-basis-proof-v1"] = (
        "source-bound-observation-basis-proof-v1"
    )
    rows: tuple[FiscalRowPolicyV1, ...]
    unsupported: tuple[FiscalUnsupportedRowFamilyV1, ...]

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def fiscal_statement_policy() -> FiscalStatementPolicyV1:
    rows: list[FiscalRowPolicyV1] = []
    for row in statement_row_definitions():
        aggregation: Aggregation
        if row.row_id == "cash_flow_beginning_balance":
            aggregation = "cash_opening"
        elif row.row_id == "cash_flow_ending_balance":
            aggregation = "cash_closing"
        elif row.statement == "balance_sheet":
            aggregation = "instant"
        else:
            aggregation = "additive_flow"
        rows.append(
            FiscalRowPolicyV1(
                row_id=row.row_id,
                statement=row.statement,
                label=row.label,
                aggregation=aggregation,
            )
        )
    return FiscalStatementPolicyV1(
        rows=tuple(rows),
        unsupported=(
            FiscalUnsupportedRowFamilyV1(
                family="eps_and_per_share",
                reason="Per-share values require a reviewed denominator and anti-dilution policy.",
            ),
            FiscalUnsupportedRowFamilyV1(
                family="weighted_average_shares",
                reason="Weighted averages require period-weighted reconstruction and are not additive.",
            ),
            FiscalUnsupportedRowFamilyV1(
                family="ratios_and_margins",
                reason="Ratios require separate numerator and denominator policies and are not additive.",
            ),
        ),
    )
