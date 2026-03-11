from __future__ import annotations

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from .base_model_income_cashflow_contracts import (
    IncomeCashflowComponentFields,
    IncomeCashflowDerivedMetricFields,
    IncomeCashflowOps,
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
