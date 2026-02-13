from pydantic import Field

from .._template.schemas import BaseValuationParams


class EvaParams(BaseValuationParams):
    current_invested_capital: float = Field(
        ..., description="Current invested capital (in millions)"
    )
    projected_evas: list[float] = Field(
        ..., description="Projected EVA values for forecast period"
    )
    wacc: float = Field(..., description="WACC (e.g., 0.10)")
    terminal_growth: float = Field(..., description="Terminal growth rate (e.g., 0.03)")
    terminal_eva: float | None = Field(
        None, description="Terminal EVA (defaults to last projection)"
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
