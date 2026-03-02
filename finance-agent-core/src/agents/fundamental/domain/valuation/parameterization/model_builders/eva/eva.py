from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....report_contract import FinancialReport
from ...types import TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from .eva_invested_capital_policy_service import resolve_eva_invested_capital_field
from .eva_output_assembly_service import (
    build_eva_params,
    build_eva_trace_inputs,
    extend_eva_missing_fields,
)


@dataclass(frozen=True)
class EvaBuilderDeps:
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    missing_field: Callable[[str, str], TraceableField[float]]
    computed_field: Callable[
        [str, float | list[float], str, str, dict[str, TraceableField]],
        TraceableField,
    ]


@dataclass(frozen=True)
class EvaBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_eva_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: EvaBuilderDeps,
) -> EvaBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    equity_tf = base.total_equity
    debt_tf = base.total_debt
    cash_tf = base.cash_and_equivalents
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    preferred_tf = base.preferred_stock

    invested_capital_tf = resolve_eva_invested_capital_field(
        equity_tf=equity_tf,
        debt_tf=debt_tf,
        cash_tf=cash_tf,
        missing_field=deps.missing_field,
        computed_field=deps.computed_field,
    )

    current_invested_capital = deps.value_or_missing(
        invested_capital_tf,
        "current_invested_capital",
        missing,
    )
    market_values = extract_filing_capital_structure_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = market_values.shares_outstanding
    cash = market_values.cash
    total_debt = market_values.total_debt
    preferred_stock = market_values.preferred_stock
    current_price = market_values.current_price
    shares_source = market_values.shares_source

    extend_eva_missing_fields(missing=missing)

    trace_inputs: dict[str, TraceInput] = build_eva_trace_inputs(
        invested_capital_tf=invested_capital_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        shares_tf=shares_tf,
    )

    params: dict[str, object] = build_eva_params(
        ticker=ticker,
        current_invested_capital=current_invested_capital,
        cash=cash,
        total_debt=total_debt,
        preferred_stock=preferred_stock,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
    )

    return EvaBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
