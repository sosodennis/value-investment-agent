from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ..report_contract import FinancialReport

TraceInput = TraceableField[float] | TraceableField[list[float]]


@dataclass(frozen=True)
class MultiplesBuilderDeps:
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]


@dataclass(frozen=True)
class MultipleBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_ev_revenue_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: MultiplesBuilderDeps,
) -> MultipleBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    revenue_tf = base.total_revenue
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    market_shares = deps.market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    revenue = deps.value_or_missing(revenue_tf, "revenue", missing)
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = deps.value_or_missing(cash_tf, "cash", missing)
    total_debt = deps.value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = deps.value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = deps.market_float(market_snapshot, "current_price")

    missing.append("ev_revenue_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": revenue_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "revenue": revenue,
        "ev_revenue_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return MultipleBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )


def build_ev_ebitda_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: MultiplesBuilderDeps,
) -> MultipleBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    ebitda_tf = base.ebitda
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    market_shares = deps.market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    ebitda = deps.value_or_missing(ebitda_tf, "ebitda", missing)
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = deps.value_or_missing(cash_tf, "cash", missing)
    total_debt = deps.value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = deps.value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = deps.market_float(market_snapshot, "current_price")

    missing.append("ev_ebitda_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": ebitda_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "ebitda": ebitda,
        "ev_ebitda_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return MultipleBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
