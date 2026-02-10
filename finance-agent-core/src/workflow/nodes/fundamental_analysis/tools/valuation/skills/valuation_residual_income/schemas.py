from pydantic import Field

from .._template.schemas import BaseValuationParams


class ResidualIncomeParams(BaseValuationParams):
    current_book_value: float = Field(
        ..., description="Current book value of equity (in millions)"
    )
    projected_residual_incomes: list[float] = Field(
        ..., description="Projected residual incomes for forecast period"
    )
    required_return: float = Field(
        ..., description="Required return on equity (e.g., 0.10)"
    )
    terminal_growth: float = Field(..., description="Terminal growth rate (e.g., 0.03)")
    terminal_residual_income: float | None = Field(
        None, description="Terminal residual income (defaults to last projection)"
    )
    shares_outstanding: float = Field(
        ..., description="Shares outstanding (in millions)"
    )
    current_price: float | None = Field(
        None, description="Current share price for upside/downside"
    )
