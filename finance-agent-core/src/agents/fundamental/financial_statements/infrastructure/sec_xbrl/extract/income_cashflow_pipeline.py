from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

from .extractor import SearchConfig, SECReportExtractor

BuildConfigFn = Callable[
    [str, list[str] | None, str | None, list[str] | None], SearchConfig
]
ResolveConfigsFn = Callable[[str], list[SearchConfig]]
ExtractFieldFn = Callable[
    [SECReportExtractor, list[SearchConfig], str, type[float]],
    TraceableField[float],
]
CalcSubtractFn = Callable[
    [str, TraceableField[float], TraceableField[float], str],
    TraceableField[float],
]
CalcRatioFn = Callable[
    [str, TraceableField[float], TraceableField[float], str],
    TraceableField[float],
]
CalcInvestedCapitalFn = Callable[
    [TraceableField[float], TraceableField[float], TraceableField[float]],
    TraceableField[float],
]
CalcNopatFn = Callable[
    [TraceableField[float], TraceableField[float]],
    TraceableField[float],
]


@dataclass(frozen=True)
class IncomeCashflowOps:
    extract_field_fn: ExtractFieldFn
    calc_subtract_fn: CalcSubtractFn
    calc_ratio_fn: CalcRatioFn
    calc_invested_capital_fn: CalcInvestedCapitalFn
    calc_nopat_fn: CalcNopatFn


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


@dataclass(slots=True)
class IncomeCashflowComponentFields:
    preferred_stock: TraceableField[float]
    total_revenue: TraceableField[float]
    operating_income: TraceableField[float]
    income_before_tax: TraceableField[float]
    interest_expense: TraceableField[float]
    depreciation_and_amortization: TraceableField[float]
    share_based_compensation: TraceableField[float]
    net_income: TraceableField[float]
    income_tax_expense: TraceableField[float]
    ebitda: TraceableField[float]
    operating_cash_flow: TraceableField[float]
    dividends_paid: TraceableField[float]


@dataclass(slots=True)
class IncomeCashflowDerivedMetricFields:
    working_capital: TraceableField[float]
    effective_tax_rate: TraceableField[float]
    interest_cost_rate: TraceableField[float]
    ebit_margin: TraceableField[float]
    net_margin: TraceableField[float]
    invested_capital: TraceableField[float]
    nopat: TraceableField[float]
    roic: TraceableField[float]


@dataclass(slots=True)
class IncomeCashflowDerivedFields:
    preferred_stock: TraceableField[float]
    total_revenue: TraceableField[float]
    operating_income: TraceableField[float]
    income_before_tax: TraceableField[float]
    interest_expense: TraceableField[float]
    depreciation_and_amortization: TraceableField[float]
    share_based_compensation: TraceableField[float]
    net_income: TraceableField[float]
    income_tax_expense: TraceableField[float]
    ebitda: TraceableField[float]
    operating_cash_flow: TraceableField[float]
    dividends_paid: TraceableField[float]
    working_capital: TraceableField[float]
    effective_tax_rate: TraceableField[float]
    interest_cost_rate: TraceableField[float]
    ebit_margin: TraceableField[float]
    net_margin: TraceableField[float]
    invested_capital: TraceableField[float]
    nopat: TraceableField[float]
    roic: TraceableField[float]


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
        build_config(
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
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


def extract_income_cashflow_component_fields(
    *,
    extractor: SECReportExtractor,
    config_bundle: IncomeCashflowConfigBundle,
    ops: IncomeCashflowOps,
) -> IncomeCashflowComponentFields:
    preferred_stock = ops.extract_field_fn(
        extractor,
        config_bundle.preferred_stock,
        "Preferred Stock",
        target_type=float,
    )
    if preferred_stock.value is None:
        preferred_stock = TraceableField(
            name="Preferred Stock",
            value=0.0,
            provenance=ManualProvenance(
                description="Assumed 0 due to no disclosure or no implementaion now"
            ),
        )

    total_revenue = ops.extract_field_fn(
        extractor,
        config_bundle.total_revenue,
        "Total Revenue",
        target_type=float,
    )
    operating_income = ops.extract_field_fn(
        extractor,
        config_bundle.operating_income,
        "Operating Income (EBIT)",
        target_type=float,
    )
    income_before_tax = ops.extract_field_fn(
        extractor,
        config_bundle.income_before_tax,
        "Income Before Tax",
        target_type=float,
    )
    interest_expense = ops.extract_field_fn(
        extractor,
        config_bundle.interest_expense,
        "Interest Expense",
        target_type=float,
    )
    depreciation_and_amortization = ops.extract_field_fn(
        extractor,
        config_bundle.depreciation_and_amortization,
        "Depreciation & Amortization",
        target_type=float,
    )
    share_based_compensation = ops.extract_field_fn(
        extractor,
        config_bundle.share_based_compensation,
        "Share-Based Compensation",
        target_type=float,
    )
    net_income = ops.extract_field_fn(
        extractor,
        config_bundle.net_income,
        "Net Income",
        target_type=float,
    )
    income_tax_expense = ops.extract_field_fn(
        extractor,
        config_bundle.income_tax_expense,
        "Income Tax Expense",
        target_type=float,
    )

    ebitda = _build_ebitda(
        operating_income=operating_income,
        depreciation_and_amortization=depreciation_and_amortization,
    )

    operating_cash_flow = ops.extract_field_fn(
        extractor,
        config_bundle.operating_cash_flow,
        "Operating Cash Flow (OCF)",
        target_type=float,
    )
    dividends_paid = ops.extract_field_fn(
        extractor,
        config_bundle.dividends_paid,
        "Dividends Paid",
        target_type=float,
    )

    return IncomeCashflowComponentFields(
        preferred_stock=preferred_stock,
        total_revenue=total_revenue,
        operating_income=operating_income,
        income_before_tax=income_before_tax,
        interest_expense=interest_expense,
        depreciation_and_amortization=depreciation_and_amortization,
        share_based_compensation=share_based_compensation,
        net_income=net_income,
        income_tax_expense=income_tax_expense,
        ebitda=ebitda,
        operating_cash_flow=operating_cash_flow,
        dividends_paid=dividends_paid,
    )


def _build_ebitda(
    *,
    operating_income: TraceableField[float],
    depreciation_and_amortization: TraceableField[float],
) -> TraceableField[float]:
    if (
        operating_income.value is not None
        and depreciation_and_amortization.value is not None
    ):
        return TraceableField(
            name="EBITDA",
            value=operating_income.value + depreciation_and_amortization.value,
            provenance=ComputedProvenance(
                op_code="EBITDA_CALC",
                expression="OperatingIncome + DepreciationAndAmortization",
                inputs={
                    "Operating Income": operating_income,
                    "Depreciation & Amortization": depreciation_and_amortization,
                },
            ),
        )
    return TraceableField(
        name="EBITDA",
        value=None,
        provenance=ManualProvenance(description="Missing Operating Income or D&A"),
    )


def build_income_cashflow_derived_metrics(
    *,
    components: IncomeCashflowComponentFields,
    current_assets: TraceableField[float],
    current_liabilities: TraceableField[float],
    total_debt: TraceableField[float],
    total_equity: TraceableField[float],
    cash_and_equivalents: TraceableField[float],
    ops: IncomeCashflowOps,
) -> IncomeCashflowDerivedMetricFields:
    working_capital = ops.calc_subtract_fn(
        "Working Capital",
        current_assets,
        current_liabilities,
        "CurrentAssets - CurrentLiabilities",
    )
    effective_tax_rate = ops.calc_ratio_fn(
        "Effective Tax Rate",
        components.income_tax_expense,
        components.income_before_tax,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    interest_cost_rate = ops.calc_ratio_fn(
        "Interest Cost Rate",
        components.interest_expense,
        total_debt,
        "InterestExpense / TotalDebt",
    )
    ebit_margin = ops.calc_ratio_fn(
        "EBIT Margin",
        components.operating_income,
        components.total_revenue,
        "OperatingIncome / Revenue",
    )
    net_margin = ops.calc_ratio_fn(
        "Net Margin",
        components.net_income,
        components.total_revenue,
        "NetIncome / Revenue",
    )
    invested_capital = ops.calc_invested_capital_fn(
        total_equity,
        total_debt,
        cash_and_equivalents,
    )
    nopat = ops.calc_nopat_fn(components.operating_income, effective_tax_rate)
    roic = ops.calc_ratio_fn(
        "ROIC",
        nopat,
        invested_capital,
        "NOPAT / InvestedCapital",
    )

    return IncomeCashflowDerivedMetricFields(
        working_capital=working_capital,
        effective_tax_rate=effective_tax_rate,
        interest_cost_rate=interest_cost_rate,
        ebit_margin=ebit_margin,
        net_margin=net_margin,
        invested_capital=invested_capital,
        nopat=nopat,
        roic=roic,
    )


def build_income_cashflow_and_derived_fields(
    *,
    extractor: SECReportExtractor,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    ops: IncomeCashflowOps,
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    cf_statement_tokens: list[str],
    usd_units: list[str],
    current_assets: TraceableField[float],
    current_liabilities: TraceableField[float],
    total_debt: TraceableField[float],
    total_equity: TraceableField[float],
    cash_and_equivalents: TraceableField[float],
) -> IncomeCashflowDerivedFields:
    config_bundle = build_income_cashflow_config_bundle(
        resolve_configs=resolve_configs,
        build_config=build_config,
        bs_statement_tokens=bs_statement_tokens,
        is_statement_tokens=is_statement_tokens,
        cf_statement_tokens=cf_statement_tokens,
        usd_units=usd_units,
    )

    components = extract_income_cashflow_component_fields(
        extractor=extractor,
        config_bundle=config_bundle,
        ops=ops,
    )

    derived_metrics = build_income_cashflow_derived_metrics(
        components=components,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        total_debt=total_debt,
        total_equity=total_equity,
        cash_and_equivalents=cash_and_equivalents,
        ops=ops,
    )

    return IncomeCashflowDerivedFields(
        preferred_stock=components.preferred_stock,
        total_revenue=components.total_revenue,
        operating_income=components.operating_income,
        income_before_tax=components.income_before_tax,
        interest_expense=components.interest_expense,
        depreciation_and_amortization=components.depreciation_and_amortization,
        share_based_compensation=components.share_based_compensation,
        net_income=components.net_income,
        income_tax_expense=components.income_tax_expense,
        ebitda=components.ebitda,
        operating_cash_flow=components.operating_cash_flow,
        dividends_paid=components.dividends_paid,
        working_capital=derived_metrics.working_capital,
        effective_tax_rate=derived_metrics.effective_tax_rate,
        interest_cost_rate=derived_metrics.interest_cost_rate,
        ebit_margin=derived_metrics.ebit_margin,
        net_margin=derived_metrics.net_margin,
        invested_capital=derived_metrics.invested_capital,
        nopat=derived_metrics.nopat,
        roic=derived_metrics.roic,
    )


__all__ = [
    "BuildConfigFn",
    "IncomeCashflowDerivedFields",
    "IncomeCashflowOps",
    "ResolveConfigsFn",
    "build_income_cashflow_and_derived_fields",
]
