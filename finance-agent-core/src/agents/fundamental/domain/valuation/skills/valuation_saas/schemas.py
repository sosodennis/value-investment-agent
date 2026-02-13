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
    shares_outstanding: float = Field(
        ..., description="Shares outstanding (in millions)"
    )
    cash: float = Field(0.0, description="Cash and equivalents (in millions)")
    total_debt: float = Field(0.0, description="Total debt (in millions)")
    preferred_stock: float = Field(0.0, description="Preferred stock (in millions)")
    current_price: float | None = Field(
        None, description="Current share price for upside/downside"
    )

    # Optional FCFE direct projection support (if provided, can compute FCFE in calculator)
    fcfe_projections: list[float] | None = Field(
        None, description="Optional FCFE projections for FCFE DCF"
    )
    required_return: float | None = Field(
        None, description="Required return on equity for FCFE (e.g., 0.10)"
    )
    terminal_growth_fcfe: float | None = Field(
        None, description="Terminal growth rate for FCFE DCF (e.g., 0.03)"
    )
