from pydantic import BaseModel, Field


class CalculatorPreview(BaseModel):
    """UI renderable preview for Calculator Agent."""

    model_type: str = Field(..., description="Type of the valuation model")
    intrinsic_value_display: str = Field(..., description="Formatted intrinsic value")
    upside_display: str = Field(..., description="Formatted upside potential")
    confidence_display: str = Field(..., description="Confidence level")
