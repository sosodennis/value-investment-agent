from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

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
