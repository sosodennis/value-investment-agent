from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....report_contract import FinancialReport, FinancialServicesExtension
from ...types import MonteCarloControls, TraceInput
from ..shared.equity_market_value_extraction_service import (
    extract_xbrl_filing_equity_market_values,
)
from ..shared.value_extraction_common_service import (
    extract_required_values,
)
from .bank_capm_policy_service import build_bank_capm_terminal_inputs
from .bank_output_assembly_service import (
    build_bank_params,
    build_bank_trace_inputs,
    collect_bank_missing_metric_names,
)
from .bank_rorwa_policy_service import (
    build_bank_rorwa_intensity,
)


@dataclass(frozen=True)
class BankBuilderDeps:
    projection_years: int
    default_market_risk_premium: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    growth_rates_from_series: Callable[
        [str, list[TraceableField[float]], int], TraceableField[list[float]]
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]], float | None
    ]
    missing_field: Callable[[str, str], TraceableField[float]]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]], MonteCarloControls
    ]


@dataclass(frozen=True)
class BankBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_bank_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: BankBuilderDeps,
) -> BankBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []

    base = latest.base
    extension = (
        latest.extension
        if isinstance(latest.extension, FinancialServicesExtension)
        else None
    )

    net_income_tf = base.net_income
    total_equity_tf = base.total_equity
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    rwa_tf = extension.risk_weighted_assets if extension else None
    tier1_tf = extension.tier1_capital_ratio if extension else None

    income_series = [report.base.net_income for report in reports]
    income_growth_tf = deps.growth_rates_from_series(
        "Net Income Growth Rates",
        income_series,
        deps.projection_years,
    )
    rwa_intensity_tf = build_bank_rorwa_intensity(
        reports=reports,
        net_income_tf=net_income_tf,
        rwa_tf=rwa_tf,
        ratio=deps.ratio,
        missing_field=deps.missing_field,
        assumptions=assumptions,
    )

    extracted_values = extract_required_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        fields={
            "initial_net_income": net_income_tf,
            "initial_capital": total_equity_tf,
        },
    )
    initial_net_income = extracted_values["initial_net_income"]
    initial_capital = extracted_values["initial_capital"]
    equity_market_values = extract_xbrl_filing_equity_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = equity_market_values.shares_outstanding
    current_price = equity_market_values.current_price
    shares_source = equity_market_values.shares_source

    missing.extend(
        collect_bank_missing_metric_names(
            income_growth_tf=income_growth_tf,
            rwa_intensity_tf=rwa_intensity_tf,
            tier1_tf=tier1_tf,
        )
    )

    capm_terminal_inputs = build_bank_capm_terminal_inputs(
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_market_risk_premium=deps.default_market_risk_premium,
        assumptions=assumptions,
    )
    risk_free_rate = capm_terminal_inputs.risk_free_rate
    beta = capm_terminal_inputs.beta
    market_risk_premium = capm_terminal_inputs.market_risk_premium
    terminal_growth_tf = capm_terminal_inputs.terminal_growth_tf

    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(
        market_snapshot,
        assumptions,
    )

    trace_inputs: dict[str, TraceInput] = build_bank_trace_inputs(
        net_income_tf=net_income_tf,
        income_growth_tf=income_growth_tf,
        rwa_intensity_tf=rwa_intensity_tf,
        tier1_tf=tier1_tf,
        total_equity_tf=total_equity_tf,
        shares_tf=shares_tf,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        terminal_growth_tf=terminal_growth_tf,
        missing_field=deps.missing_field,
    )

    params: dict[str, object] = build_bank_params(
        ticker=ticker,
        initial_net_income=initial_net_income,
        income_growth_rates=income_growth_tf.value,
        rwa_intensity=rwa_intensity_tf.value,
        tier1_target_ratio=tier1_tf.value if tier1_tf is not None else None,
        initial_capital=initial_capital,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        terminal_growth=terminal_growth_tf.value,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return BankBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
