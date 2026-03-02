from __future__ import annotations

from collections.abc import Callable

from src.shared.kernel.traceable import TraceableField

from ...types import TraceInput
from ..shared.common_output_assembly_service import (
    build_capm_market_params,
    build_capm_market_trace_inputs,
    build_equity_value_params,
    build_monte_carlo_params,
    build_sec_xbrl_base_params,
    build_shares_trace_inputs,
    resolve_optional_trace_input,
)
from ..shared.missing_metrics_service import collect_missing_metric_names


def collect_bank_missing_metric_names(
    *,
    income_growth_tf: TraceableField[list[float]],
    rwa_intensity_tf: TraceableField[float],
    tier1_tf: TraceableField[float] | None,
) -> list[str]:
    return collect_missing_metric_names(
        metric_fields={
            "income_growth_rates": income_growth_tf,
            "rwa_intensity": rwa_intensity_tf,
            "tier1_target_ratio": tier1_tf,
        }
    )


def build_bank_trace_inputs(
    *,
    net_income_tf: TraceableField[float],
    income_growth_tf: TraceableField[list[float]],
    rwa_intensity_tf: TraceableField[float],
    tier1_tf: TraceableField[float] | None,
    total_equity_tf: TraceableField[float],
    shares_tf: TraceableField[float],
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    terminal_growth_tf: TraceableField[float],
    missing_field: Callable[[str, str], TraceableField[float]],
) -> dict[str, TraceInput]:
    return {
        "initial_net_income": net_income_tf,
        "income_growth_rates": income_growth_tf,
        "rwa_intensity": rwa_intensity_tf,
        "tier1_target_ratio": resolve_optional_trace_input(
            trace_input=tier1_tf,
            field_name="Tier1 Target Ratio",
            missing_reason="Missing Tier 1 ratio",
            missing_field=missing_field,
        ),
        "initial_capital": total_equity_tf,
        **build_shares_trace_inputs(shares_tf=shares_tf),
        **build_capm_market_trace_inputs(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
            risk_free_description="Market-derived risk-free rate for CAPM",
            beta_description="Market-derived equity beta for CAPM",
            market_risk_premium_description="Policy market risk premium for CAPM",
        ),
        "terminal_growth": terminal_growth_tf,
    }


def build_bank_params(
    *,
    ticker: str | None,
    initial_net_income: float | None,
    income_growth_rates: list[float] | None,
    rwa_intensity: float | None,
    tier1_target_ratio: float | None,
    initial_capital: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    terminal_growth: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_sec_xbrl_base_params(ticker=ticker),
        "initial_net_income": initial_net_income,
        "income_growth_rates": income_growth_rates,
        "rwa_intensity": rwa_intensity,
        "tier1_target_ratio": tier1_target_ratio,
        "initial_capital": initial_capital,
        **build_equity_value_params(
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_capm_market_params(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
        ),
        "cost_of_equity_strategy": "capm",
        "cost_of_equity": None,
        "cost_of_equity_override": None,
        "terminal_growth": terminal_growth,
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }
