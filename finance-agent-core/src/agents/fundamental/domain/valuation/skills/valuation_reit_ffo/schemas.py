from pydantic import Field

from .._template.schemas import BaseValuationParams


class ReitFfoParams(BaseValuationParams):
    ffo: float = Field(..., description="Funds From Operations (in millions)")
    ffo_multiple: float = Field(..., description="Selected FFO multiple")
    depreciation_and_amortization: float = Field(
        0.0, description="Depreciation and amortization (in millions)"
    )
    maintenance_capex_ratio: float = Field(
        0.8, description="Maintenance CapEx ratio applied to depreciation"
    )
    cash: float = Field(0.0, description="Cash and equivalents (in millions)")
    total_debt: float = Field(0.0, description="Total debt (in millions)")
    preferred_stock: float = Field(0.0, description="Preferred stock (in millions)")
    shares_outstanding: float = Field(
        ..., description="Shares outstanding (in millions)"
    )
    current_price: float | None = Field(
        None, description="Current share price for upside/downside"
    )
    monte_carlo_iterations: int = Field(
        0, ge=0, description="Monte Carlo iteration count (0 disables MC)"
    )
    monte_carlo_seed: int | None = Field(
        None, description="Optional seed for deterministic Monte Carlo runs"
    )
    occupancy_rate_left: float = Field(
        0.70, ge=0.0, le=1.0, description="Triangular left bound for occupancy rate"
    )
    occupancy_rate_mode: float = Field(
        0.90, ge=0.0, le=1.0, description="Triangular mode for occupancy rate"
    )
    occupancy_rate_right: float = Field(
        0.98, ge=0.0, le=1.0, description="Triangular right bound for occupancy rate"
    )
    cap_rate_std: float = Field(
        0.01, gt=0, le=0.10, description="Std dev for cap rate in Monte Carlo"
    )
    corr_occupancy_cap_rate: float = Field(
        -0.40,
        ge=-0.99,
        le=0.99,
        description="Correlation between occupancy and cap rate",
    )
