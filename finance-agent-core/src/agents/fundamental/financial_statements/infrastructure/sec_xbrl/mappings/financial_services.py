from __future__ import annotations

from ..extractor import SearchType
from ..mapping import (
    BS_STATEMENT_TOKENS,
    IS_STATEMENT_TOKENS,
    RATIO_UNITS,
    USD_UNITS,
    FieldSpec,
    XbrlMappingRegistry,
)


def register_financial_services_fields(registry: XbrlMappingRegistry) -> None:
    # ---- Financial services extension ----
    registry.register(
        "loans_and_leases",
        FieldSpec(
            name="Loans and Leases",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LoansAndLeasesReceivableNetReportedAmount",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "deposits",
        FieldSpec(
            name="Deposits",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:Deposits",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "allowance_for_credit_losses",
        FieldSpec(
            name="Allowance for Credit Losses",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:FinancingReceivableAllowanceForCreditLosses",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest",
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:AllowanceForLoanAndLeaseLosses",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "interest_income",
        FieldSpec(
            name="Interest Income",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestIncome",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestIncomeOperating",
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestIncomeExpenseNet",
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "interest_expense_financial",
        FieldSpec(
            name="Interest Expense",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestExpenseOperating",
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:InterestExpenseNonoperating",
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "provision_for_loan_losses",
        FieldSpec(
            name="Provision for Loan Losses",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:ProvisionForCreditLosses",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "risk_weighted_assets",
        FieldSpec(
            name="Risk-Weighted Assets",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:RiskWeightedAssets",
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "tier1_capital_ratio",
        FieldSpec(
            name="Tier 1 Capital Ratio",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:Tier1CapitalRatio",
                    period_type="instant",
                    unit_whitelist=RATIO_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:Tier1RiskBasedCapitalRatio",
                    period_type="instant",
                    unit_whitelist=RATIO_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:TierOneRiskBasedCapitalToRiskWeightedAssets",
                    period_type="instant",
                    unit_whitelist=RATIO_UNITS,
                ),
            ],
        ),
    )
