from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ..report_contract import FinancialReport

TraceInput = TraceableField[float] | TraceableField[list[float]]


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
    market_shares = deps.market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    preferred_tf = base.preferred_stock

    if equity_tf.value is None or debt_tf.value is None or cash_tf.value is None:
        invested_capital_tf = deps.missing_field(
            "Invested Capital", "Missing equity, debt, or cash"
        )
    else:
        invested_capital_tf = deps.computed_field(
            "Invested Capital",
            float(equity_tf.value) + float(debt_tf.value) - float(cash_tf.value),
            "INVESTED_CAPITAL",
            "TotalEquity + TotalDebt - Cash",
            {
                "Total Equity": equity_tf,
                "Total Debt": debt_tf,
                "Cash": cash_tf,
            },
        )

    current_invested_capital = deps.value_or_missing(
        invested_capital_tf, "current_invested_capital", missing
    )
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = deps.value_or_missing(cash_tf, "cash", missing)
    total_debt = deps.value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = deps.value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = deps.market_float(market_snapshot, "current_price")

    missing.extend(["projected_evas", "wacc", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_invested_capital": invested_capital_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_invested_capital": current_invested_capital,
        "projected_evas": None,
        "wacc": None,
        "terminal_growth": None,
        "terminal_eva": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return EvaBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
