from __future__ import annotations

from dataclasses import dataclass

from .base_model_income_cashflow_contracts import BuildConfigFn, ResolveConfigsFn
from .extractor import SearchConfig


@dataclass(frozen=True)
class IncomeCashflowConfigBundle:
    preferred_stock: list[SearchConfig]
    total_revenue: list[SearchConfig]
    operating_income: list[SearchConfig]
    income_before_tax: list[SearchConfig]
    interest_expense: list[SearchConfig]
    depreciation_and_amortization: list[SearchConfig]
    share_based_compensation: list[SearchConfig]
    net_income: list[SearchConfig]
    income_tax_expense: list[SearchConfig]
    operating_cash_flow: list[SearchConfig]
    dividends_paid: list[SearchConfig]


def build_income_cashflow_config_bundle(
    *,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    cf_statement_tokens: list[str],
    usd_units: list[str],
) -> IncomeCashflowConfigBundle:
    preferred_stock = resolve_configs("preferred_stock") or [
        build_config(
            "us-gaap:PreferredStockValue",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:PreferredStockCarryingAmount",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:PreferredStock", bs_statement_tokens, "instant", usd_units
        ),
    ]

    total_revenue = resolve_configs("total_revenue") or [
        build_config("us-gaap:Revenues", is_statement_tokens, "duration", usd_units),
        build_config(
            "us-gaap:SalesRevenueNet",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    operating_income = resolve_configs("operating_income") or [
        build_config(
            "us-gaap:OperatingIncomeLoss",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:OperatingIncomeLossContinuingOperations",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    income_before_tax = resolve_configs("income_before_tax") or [
        build_config(
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:IncomeBeforeTax",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:PretaxIncome",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    interest_expense = resolve_configs("interest_expense") or [
        build_config(
            "us-gaap:InterestExpense",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:InterestExpenseDebt",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    depreciation_and_amortization = resolve_configs(
        "depreciation_and_amortization"
    ) or [
        build_config(
            "us-gaap:DepreciationAndAmortization",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DepreciationAndAmortization",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DepreciationDepletionAndAmortization",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DepreciationDepletionAndAmortization",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DepreciationAmortizationAndAccretionNet",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DepreciationAmortizationAndAccretionNet",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:Depreciation",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:Depreciation",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    share_based_compensation = resolve_configs("share_based_compensation") or [
        build_config(
            "us-gaap:ShareBasedCompensation",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:ShareBasedCompensation",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:ShareBasedCompensationExpense",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:ShareBasedCompensationExpense",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:ShareBasedCompensationCost",
            is_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:ShareBasedCompensationCost",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
    ]

    net_income = resolve_configs("net_income") or [
        build_config(
            "us-gaap:NetIncomeLoss", is_statement_tokens, "duration", usd_units
        )
    ]

    income_tax_expense = resolve_configs("income_tax_expense") or [
        build_config(
            "us-gaap:IncomeTaxExpenseBenefit",
            is_statement_tokens,
            "duration",
            usd_units,
        )
    ]

    operating_cash_flow = resolve_configs("operating_cash_flow") or [
        build_config(
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            cf_statement_tokens,
            "duration",
            usd_units,
        )
    ]

    dividends_paid = resolve_configs("dividends_paid") or [
        build_config(
            "us-gaap:PaymentsOfDividends",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:PaymentsOfDividendsCommonStock",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DividendsCommonStockCash",
            cf_statement_tokens,
            "duration",
            usd_units,
        ),
        build_config(
            "us-gaap:DividendsPaid", cf_statement_tokens, "duration", usd_units
        ),
    ]

    return IncomeCashflowConfigBundle(
        preferred_stock=preferred_stock,
        total_revenue=total_revenue,
        operating_income=operating_income,
        income_before_tax=income_before_tax,
        interest_expense=interest_expense,
        depreciation_and_amortization=depreciation_and_amortization,
        share_based_compensation=share_based_compensation,
        net_income=net_income,
        income_tax_expense=income_tax_expense,
        operating_cash_flow=operating_cash_flow,
        dividends_paid=dividends_paid,
    )
