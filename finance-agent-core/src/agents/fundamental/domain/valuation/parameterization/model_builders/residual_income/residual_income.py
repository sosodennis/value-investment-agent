from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....report_contract import FinancialReport
from ...types import TraceInput
from ..shared.equity_market_value_extraction_service import (
    extract_filing_equity_market_values,
)
from .residual_income_output_assembly_service import (
    build_residual_income_params,
    build_residual_income_trace_inputs,
    extend_residual_income_missing_fields,
)


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
    current_book_value = deps.value_or_missing(
        book_value_tf,
        "current_book_value",
        missing,
    )
    equity_market_values = extract_filing_equity_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = equity_market_values.shares_outstanding
    current_price = equity_market_values.current_price
    shares_source = equity_market_values.shares_source

    extend_residual_income_missing_fields(missing=missing)

    trace_inputs: dict[str, TraceInput] = build_residual_income_trace_inputs(
        book_value_tf=book_value_tf,
        shares_tf=shares_tf,
    )

    params: dict[str, object] = build_residual_income_params(
        ticker=ticker,
        current_book_value=current_book_value,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
    )

    return ResidualIncomeBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
