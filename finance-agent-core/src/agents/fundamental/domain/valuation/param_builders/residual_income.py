from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ..report_contract import FinancialReport

TraceInput = TraceableField[float] | TraceableField[list[float]]


@dataclass(frozen=True)
class ResidualIncomeBuilderDeps:
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
class ResidualIncomeBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_residual_income_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: ResidualIncomeBuilderDeps,
) -> ResidualIncomeBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    book_value_tf = base.total_equity
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    market_shares = deps.market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )

    current_book_value = deps.value_or_missing(
        book_value_tf, "current_book_value", missing
    )
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    current_price = deps.market_float(market_snapshot, "current_price")

    missing.extend(["projected_residual_incomes", "required_return", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_book_value": book_value_tf,
        "shares_outstanding": shares_tf,
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_book_value": current_book_value,
        "projected_residual_incomes": None,
        "required_return": None,
        "terminal_growth": None,
        "terminal_residual_income": None,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return ResidualIncomeBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
