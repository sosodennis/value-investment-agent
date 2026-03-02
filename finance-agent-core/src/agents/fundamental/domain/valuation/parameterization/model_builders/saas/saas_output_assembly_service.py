from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...types import TraceInput
from ..shared.common_output_assembly_service import (
    build_base_params,
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_capm_market_params,
    build_capm_market_trace_inputs,
    build_monte_carlo_params,
)
from ..shared.missing_metrics_service import collect_missing_metric_names


def collect_saas_missing_metric_names(
    *,
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
) -> list[str]:
    return collect_missing_metric_names(
        metric_fields={
            "growth_rates": growth_rates_tf,
            "operating_margins": operating_margins_tf,
            "tax_rate": tax_rate_tf,
            "da_rates": da_rates_tf,
            "capex_rates": capex_rates_tf,
            "wc_rates": wc_rates_tf,
            "sbc_rates": sbc_rates_tf,
        }
    )


def build_saas_trace_inputs(
    *,
    revenue_tf: TraceableField[float],
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
    wacc_tf: TraceableField[float],
    terminal_growth_tf: TraceableField[float],
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "initial_revenue": revenue_tf,
        "growth_rates": growth_rates_tf,
        "operating_margins": operating_margins_tf,
        "tax_rate": tax_rate_tf,
        "da_rates": da_rates_tf,
        "capex_rates": capex_rates_tf,
        "wc_rates": wc_rates_tf,
        "sbc_rates": sbc_rates_tf,
        "wacc": wacc_tf,
        "terminal_growth": terminal_growth_tf,
        **build_capm_market_trace_inputs(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
            risk_free_description="Market-derived risk-free rate for SaaS CAPM",
            beta_description="Market-derived beta for SaaS CAPM",
            market_risk_premium_description="Policy market risk premium for SaaS CAPM",
        ),
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
    }


def build_saas_rationale(assumptions: list[str]) -> str:
    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)
    return rationale


def build_saas_params(
    *,
    ticker: str | None,
    rationale: str,
    initial_revenue: float | None,
    growth_rates: list[float] | None,
    operating_margins: list[float] | None,
    tax_rate: float | None,
    da_rates: list[float] | None,
    capex_rates: list[float] | None,
    wc_rates: list[float] | None,
    sbc_rates: list[float] | None,
    wacc: float | None,
    terminal_growth: float | None,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    shares_outstanding: float | None,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    current_price: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_base_params(
            ticker=ticker,
            rationale=rationale,
        ),
        "initial_revenue": initial_revenue,
        "growth_rates": growth_rates,
        "operating_margins": operating_margins,
        "tax_rate": tax_rate,
        "da_rates": da_rates,
        "capex_rates": capex_rates,
        "wc_rates": wc_rates,
        "sbc_rates": sbc_rates,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        **build_capm_market_params(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
        ),
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }
