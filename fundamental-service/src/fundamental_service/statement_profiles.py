"""The registered major-row annual statement profile and executable identity."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .serialization import sha256_digest
from .statement_contracts import StatementProfileV1, StatementRowDefinitionV1


_ROWS = (
    StatementRowDefinitionV1(
        row_id="revenue",
        statement="income_statement",
        label="Revenue",
        value_period_role="duration",
        concepts=(
            "us-gaap:Revenues",
            "us-gaap:SalesRevenueNet",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        ),
    ),
    StatementRowDefinitionV1(
        row_id="cost_of_revenue",
        statement="income_statement",
        label="Cost of revenue",
        value_period_role="duration",
        concepts=("us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold"),
    ),
    StatementRowDefinitionV1(
        row_id="gross_profit",
        statement="income_statement",
        label="Gross profit",
        value_period_role="duration",
        concepts=("us-gaap:GrossProfit",),
    ),
    StatementRowDefinitionV1(
        row_id="operating_income",
        statement="income_statement",
        label="Operating income",
        value_period_role="duration",
        concepts=("us-gaap:OperatingIncomeLoss",),
    ),
    StatementRowDefinitionV1(
        row_id="income_before_tax",
        statement="income_statement",
        label="Income before tax",
        value_period_role="duration",
        concepts=(
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
    ),
    StatementRowDefinitionV1(
        row_id="income_tax_expense",
        statement="income_statement",
        label="Income tax",
        value_period_role="duration",
        concepts=("us-gaap:IncomeTaxExpenseBenefit",),
    ),
    StatementRowDefinitionV1(
        row_id="net_income",
        statement="income_statement",
        label="Net income",
        value_period_role="duration",
        concepts=("us-gaap:NetIncomeLoss",),
    ),
    StatementRowDefinitionV1(
        row_id="cash_and_equivalents",
        statement="balance_sheet",
        label="Cash and equivalents",
        value_period_role="period_end",
        concepts=("us-gaap:CashAndCashEquivalentsAtCarryingValue",),
    ),
    StatementRowDefinitionV1(
        row_id="operating_current_receivables",
        statement="balance_sheet",
        label="Accounts receivable",
        value_period_role="period_end",
        concepts=("us-gaap:AccountsReceivableNetCurrent",),
    ),
    StatementRowDefinitionV1(
        row_id="inventory",
        statement="balance_sheet",
        label="Inventory",
        value_period_role="period_end",
        concepts=("us-gaap:InventoryNet",),
    ),
    StatementRowDefinitionV1(
        row_id="current_assets",
        statement="balance_sheet",
        label="Current assets",
        value_period_role="period_end",
        concepts=("us-gaap:AssetsCurrent",),
    ),
    StatementRowDefinitionV1(
        row_id="property_plant_and_equipment",
        statement="balance_sheet",
        label="Property, plant and equipment",
        value_period_role="period_end",
        concepts=("us-gaap:PropertyPlantAndEquipmentNet",),
    ),
    StatementRowDefinitionV1(
        row_id="total_assets",
        statement="balance_sheet",
        label="Total assets",
        value_period_role="period_end",
        concepts=("us-gaap:Assets",),
    ),
    StatementRowDefinitionV1(
        row_id="operating_current_payables",
        statement="balance_sheet",
        label="Accounts payable",
        value_period_role="period_end",
        concepts=("us-gaap:AccountsPayableCurrent",),
    ),
    StatementRowDefinitionV1(
        row_id="current_liabilities",
        statement="balance_sheet",
        label="Current liabilities",
        value_period_role="period_end",
        concepts=("us-gaap:LiabilitiesCurrent",),
    ),
    StatementRowDefinitionV1(
        row_id="total_liabilities",
        statement="balance_sheet",
        label="Total liabilities",
        value_period_role="period_end",
        concepts=("us-gaap:Liabilities",),
    ),
    StatementRowDefinitionV1(
        row_id="total_equity",
        statement="balance_sheet",
        label="Total equity",
        value_period_role="period_end",
        concepts=("us-gaap:StockholdersEquity",),
    ),
    StatementRowDefinitionV1(
        row_id="liabilities_and_equity",
        statement="balance_sheet",
        label="Liabilities and equity",
        value_period_role="period_end",
        concepts=("us-gaap:LiabilitiesAndStockholdersEquity",),
    ),
    StatementRowDefinitionV1(
        row_id="operating_cash_flow",
        statement="cash_flow",
        label="Operating cash flow",
        value_period_role="duration",
        concepts=("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
    ),
    StatementRowDefinitionV1(
        row_id="investing_cash_flow",
        statement="cash_flow",
        label="Investing cash flow",
        value_period_role="duration",
        concepts=("us-gaap:NetCashProvidedByUsedInInvestingActivities",),
    ),
    StatementRowDefinitionV1(
        row_id="financing_cash_flow",
        statement="cash_flow",
        label="Financing cash flow",
        value_period_role="duration",
        concepts=("us-gaap:NetCashProvidedByUsedInFinancingActivities",),
    ),
    StatementRowDefinitionV1(
        row_id="effect_of_exchange_rates_on_cash",
        statement="cash_flow",
        label="Effect of exchange rates",
        value_period_role="duration",
        concepts=(
            "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents",
            "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        ),
    ),
    StatementRowDefinitionV1(
        row_id="net_change_in_cash",
        statement="cash_flow",
        label="Net change in cash",
        value_period_role="duration",
        concepts=(
            "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
            "us-gaap:CashAndCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        ),
    ),
    StatementRowDefinitionV1(
        row_id="cash_flow_beginning_balance",
        statement="cash_flow",
        label="Beginning cash balance",
        value_period_role="day_before_period_start",
        concepts=(
            "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        ),
    ),
    StatementRowDefinitionV1(
        row_id="cash_flow_ending_balance",
        statement="cash_flow",
        label="Ending cash balance",
        value_period_role="period_end",
        concepts=(
            "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        ),
    ),
)


def statement_executable_digest() -> str:
    root = Path(__file__).parent
    names = (
        "statement_profiles.py",
        "statement_contracts.py",
        "annual_statements.py",
        "facts.py",
        "xbrl_precision.py",
        "numerical_policy.py",
    )
    return sha256_digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    )


def annual_statement_profile(*, executable_digest: str) -> StatementProfileV1:
    return StatementProfileV1(
        profile_id="us-gaap-nonfinancial-annual-v1",
        contract_version="fundamental.annual-statements.v1",
        rows=_ROWS,
        selection_policy="canonical-pit-exact-row-key-v1",
        reconciliation_policy="reported-decimals-half-unit-sum-v1",
        comparability_policy="actual-annual-periods-no-annualization-v1",
        executable_digest=executable_digest,
    )


def statement_row_definitions() -> tuple[StatementRowDefinitionV1, ...]:
    return _ROWS
