from typing import Literal

from pydantic import Field

from .._template.schemas import BaseValuationParams


class BankParams(BaseValuationParams):
    initial_net_income: float = Field(
        ..., description="Most recent annual Net Income (in millions)"
    )
    income_growth_rates: list[float] = Field(
        ..., description="Projected Net Income growth rates"
    )
    rwa_intensity: float = Field(
        ...,
        description="RoRWA (Return on Risk Weighted Assets) or Income/RWA ratio. Used to project RWA growth.",
    )
    tier1_target_ratio: float = Field(
        ..., description="Target Tier 1 Capital Ratio (e.g., 0.12)"
    )
    initial_capital: float = Field(..., description="Current Tier 1 Capital")
    risk_free_rate: float = Field(..., description="Risk-free rate (annualized)")
    beta: float = Field(..., description="Equity beta for CAPM")
    market_risk_premium: float = Field(0.05, description="Market risk premium for CAPM")
    cost_of_equity_strategy: Literal["capm", "override"] = Field(
        "capm", description="Cost of equity resolution strategy"
    )
    cost_of_equity: float | None = Field(
        None, description="Legacy/manual cost of equity input (optional)"
    )
    cost_of_equity_override: float | None = Field(
        None, description="Manual override for cost of equity"
    )
    terminal_growth: float = Field(..., description="Terminal growth rate")
    monte_carlo_iterations: int = Field(
        0, ge=0, description="Monte Carlo iteration count (0 disables MC)"
    )
    monte_carlo_seed: int | None = Field(
        None, description="Optional seed for deterministic Monte Carlo runs"
    )
    provision_rate_mean: float = Field(
        0.02, ge=0, le=0.30, description="Mean bad debt provision rate for MC"
    )
    provision_rate_std: float = Field(
        0.01, gt=0, le=0.10, description="Std dev for bad debt provision rate"
    )
    income_growth_shock_std: float = Field(
        0.03, gt=0, le=0.30, description="Std dev for income growth shock"
    )
    risk_free_rate_std: float = Field(
        0.01, gt=0, le=0.10, description="Std dev for risk-free rate in MC"
    )
    terminal_growth_std: float = Field(
        0.005, gt=0, le=0.05, description="Std dev for terminal growth in MC"
    )
    corr_risk_free_terminal_growth: float = Field(
        0.30,
        ge=-0.99,
        le=0.99,
        description="Correlation between risk-free rate and terminal growth",
    )
