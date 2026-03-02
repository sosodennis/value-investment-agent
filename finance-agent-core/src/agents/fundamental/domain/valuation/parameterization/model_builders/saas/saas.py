from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....report_contract import FinancialReport
from ...types import MonteCarloControls, TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from .saas_capm_policy_service import build_saas_capm_terminal_inputs
from .saas_operating_rates_policy_service import build_saas_operating_rates
from .saas_output_assembly_service import (
    build_saas_params,
    build_saas_rationale,
    build_saas_trace_inputs,
    collect_saas_missing_metric_names,
)


@dataclass(frozen=True)
class SaasBuilderDeps:
    projection_years: int
    default_market_risk_premium: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    build_growth_rates: Callable[
        [list[TraceableField[float]], Mapping[str, object] | None, list[str]],
        TraceableField[list[float]],
    ]
    repeat_rate: Callable[
        [str, TraceableField[float], int], TraceableField[list[float]]
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        MonteCarloControls,
    ]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class SaasBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_saas_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: SaasBuilderDeps,
) -> SaasBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    revenue_tf = base.total_revenue
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    operating_rates = build_saas_operating_rates(
        latest=latest,
        reports=reports,
        revenue_tf=revenue_tf,
        ratio=deps.ratio,
        subtract=deps.subtract,
        missing_field=deps.missing_field,
        assumptions=assumptions,
    )
    margin_tf = operating_rates.margin_tf
    tax_rate_tf = operating_rates.tax_rate_tf
    da_rate_tf = operating_rates.da_rate_tf
    capex_rate_tf = operating_rates.capex_rate_tf
    sbc_rate_tf = operating_rates.sbc_rate_tf
    wc_rate_tf = operating_rates.wc_rate_tf

    revenue_series = [report.base.total_revenue for report in reports]
    growth_rates_tf = deps.build_growth_rates(
        revenue_series, market_snapshot, assumptions
    )

    operating_margins_tf = deps.repeat_rate(
        "Operating Margins", margin_tf, deps.projection_years
    )
    da_rates_tf = deps.repeat_rate("D&A Rates", da_rate_tf, deps.projection_years)
    capex_rates_tf = deps.repeat_rate(
        "CapEx Rates", capex_rate_tf, deps.projection_years
    )
    wc_rates_tf = deps.repeat_rate("WC Rates", wc_rate_tf, deps.projection_years)
    sbc_rates_tf = deps.repeat_rate("SBC Rates", sbc_rate_tf, deps.projection_years)

    initial_revenue = deps.value_or_missing(
        revenue_tf,
        "initial_revenue",
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
    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(market_snapshot, assumptions)

    missing.extend(
        collect_saas_missing_metric_names(
            growth_rates_tf=growth_rates_tf,
            operating_margins_tf=operating_margins_tf,
            tax_rate_tf=tax_rate_tf,
            da_rates_tf=da_rates_tf,
            capex_rates_tf=capex_rates_tf,
            wc_rates_tf=wc_rates_tf,
            sbc_rates_tf=sbc_rates_tf,
        )
    )

    capm_terminal_inputs = build_saas_capm_terminal_inputs(
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_market_risk_premium=deps.default_market_risk_premium,
        assumptions=assumptions,
    )
    risk_free_rate = capm_terminal_inputs.risk_free_rate
    beta = capm_terminal_inputs.beta
    market_risk_premium = capm_terminal_inputs.market_risk_premium
    wacc_tf = capm_terminal_inputs.wacc_tf
    terminal_growth_tf = capm_terminal_inputs.terminal_growth_tf

    trace_inputs: dict[str, TraceInput] = build_saas_trace_inputs(
        revenue_tf=revenue_tf,
        growth_rates_tf=growth_rates_tf,
        operating_margins_tf=operating_margins_tf,
        tax_rate_tf=tax_rate_tf,
        da_rates_tf=da_rates_tf,
        capex_rates_tf=capex_rates_tf,
        wc_rates_tf=wc_rates_tf,
        sbc_rates_tf=sbc_rates_tf,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        shares_tf=shares_tf,
    )

    rationale = build_saas_rationale(assumptions)
    params: dict[str, object] = build_saas_params(
        ticker=ticker,
        rationale=rationale,
        initial_revenue=initial_revenue,
        growth_rates=growth_rates_tf.value,
        operating_margins=operating_margins_tf.value,
        tax_rate=tax_rate_tf.value,
        da_rates=da_rates_tf.value,
        capex_rates=capex_rates_tf.value,
        wc_rates=wc_rates_tf.value,
        sbc_rates=sbc_rates_tf.value,
        wacc=wacc_tf.value,
        terminal_growth=terminal_growth_tf.value,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        shares_outstanding=shares_outstanding,
        cash=cash,
        total_debt=total_debt,
        preferred_stock=preferred_stock,
        current_price=current_price,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return SaasBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
