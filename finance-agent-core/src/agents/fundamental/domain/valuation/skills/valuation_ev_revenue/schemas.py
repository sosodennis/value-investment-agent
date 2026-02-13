from pydantic import Field

from .._template.schemas import BaseValuationParams


class EVRevenueParams(BaseValuationParams):
    revenue: float = Field(..., description="LTM revenue (in millions)")
    ev_revenue_multiple: float = Field(..., description="Selected EV/Revenue multiple")
    cash: float = Field(0.0, description="Cash and equivalents (in millions)")
    total_debt: float = Field(0.0, description="Total debt (in millions)")
    preferred_stock: float = Field(0.0, description="Preferred stock (in millions)")
    shares_outstanding: float = Field(
        ..., description="Shares outstanding (in millions)"
    )
    current_price: float | None = Field(
        None, description="Current share price for upside/downside"
    )
