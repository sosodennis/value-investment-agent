from pydantic import Field

from .._template.schemas import BaseValuationParams


class SaaSParams(BaseValuationParams):
    initial_revenue: float = Field(
        ..., description="Most recent annual revenue (in millions)"
    )
    growth_rates: list[float] = Field(
        ...,
        min_items=5,
        max_items=10,
        description="Projected revenue growth rates for the next 5-10 years (e.g., [0.20, 0.18, ...])",
    )
    operating_margins: list[float] = Field(
        ...,
        description="Projected operating margins (EBIT margin) for the projection period",
    )
    tax_rate: float = Field(..., description="Effective tax rate (e.g., 0.21)")
    da_rates: list[float] = Field(
        ..., description="Depreciation & Amortization as % of Revenue"
    )
    capex_rates: list[float] = Field(..., description="CapEx as % of Revenue")
    wc_rates: list[float] = Field(
        ..., description="Change in Working Capital as % of Revenue Change/Revenue"
    )
    sbc_rates: list[float] = Field(
        ..., description="Stock-Based Compensation as % of Revenue"
    )
    wacc: float = Field(
        ..., description="Weighted Average Cost of Capital (e.g., 0.10)"
    )
    terminal_growth: float = Field(..., description="Terminal growth rate (e.g., 0.03)")
