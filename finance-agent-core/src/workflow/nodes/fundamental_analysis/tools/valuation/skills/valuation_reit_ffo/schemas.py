from pydantic import Field

from .._template.schemas import BaseValuationParams


class ReitFfoParams(BaseValuationParams):
    ffo: float = Field(..., description="Funds From Operations (in millions)")
    ffo_multiple: float = Field(..., description="Selected FFO multiple")
    cash: float = Field(0.0, description="Cash and equivalents (in millions)")
    total_debt: float = Field(0.0, description="Total debt (in millions)")
    preferred_stock: float = Field(0.0, description="Preferred stock (in millions)")
    shares_outstanding: float = Field(
        ..., description="Shares outstanding (in millions)"
    )
    current_price: float | None = Field(
        None, description="Current share price for upside/downside"
    )
