from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.agents.fundamental.core_valuation.domain.parameterization.types import (
    TraceInput,
)


class DcfGraph(Protocol):
    def calculate(
        self,
        inputs: dict[str, object],
        trace: bool = False,
    ) -> dict[str, object]: ...


class DcfVariantParams(Protocol):
    ticker: str
    initial_revenue: float
    growth_rates: list[float]
    operating_margins: list[float]
    tax_rate: float
    da_rates: list[float]
    capex_rates: list[float]
    wc_rates: list[float]
    sbc_rates: list[float]
    wacc: float
    terminal_growth: float
    cash: float
    total_debt: float
    preferred_stock: float
    shares_outstanding: float
    current_price: float
    trace_inputs: dict[str, TraceInput]
    monte_carlo_iterations: int
    monte_carlo_seed: int
    monte_carlo_sampler: str
    growth_shock_std: float
    margin_shock_std: float
    wacc_std: float
    terminal_growth_std: float
    corr_growth_margin: float
    corr_wacc_terminal_growth: float


@dataclass(frozen=True)
class DcfMonteCarloPolicy:
    growth_std_scale: float
    growth_std_min: float
    growth_clip_min: float
    growth_clip_max: float
    margin_std_scale: float
    margin_std_min: float
    margin_clip_min: float
    margin_clip_max: float
    wacc_min: float
    wacc_max: float
    terminal_min: float
    terminal_max: float


DcfGraphFactory = Callable[[], DcfGraph]
