from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from ....report_contract import FinancialReport
from ...types import TraceInput
from ..shared.market_value_extraction import (
    extract_filing_capital_structure_market_values,
)
from ..shared.parameter_assembly_service import (
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_sec_xbrl_base_params,
)


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


@dataclass(frozen=True)
class EvMultipleTargetSpec:
    metric_param: str
    multiple_param: str


def _build_ev_multiple_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: MultiplesBuilderDeps,
    target_metric_tf: TraceableField[float],
    target_spec: EvMultipleTargetSpec,
) -> MultipleBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    target_metric = deps.value_or_missing(
        target_metric_tf,
        target_spec.metric_param,
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

    missing.append(target_spec.multiple_param)

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": target_metric_tf,
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
    }

    params: dict[str, object] = {
        **build_sec_xbrl_base_params(ticker=ticker),
        target_spec.metric_param: target_metric,
        target_spec.multiple_param: None,
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
    }

    return MultipleBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )


def build_ev_revenue_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: MultiplesBuilderDeps,
) -> MultipleBuildPayload:
    return _build_ev_multiple_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=deps,
        target_metric_tf=latest.base.total_revenue,
        target_spec=EvMultipleTargetSpec(
            metric_param="revenue",
            multiple_param="ev_revenue_multiple",
        ),
    )


def build_ev_ebitda_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: MultiplesBuilderDeps,
) -> MultipleBuildPayload:
    return _build_ev_multiple_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=deps,
        target_metric_tf=latest.base.ebitda,
        target_spec=EvMultipleTargetSpec(
            metric_param="ebitda",
            multiple_param="ev_ebitda_multiple",
        ),
    )
