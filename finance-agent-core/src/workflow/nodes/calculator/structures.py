from pydantic import BaseModel, Field


class CalculationOutput(BaseModel):
    """Output from the Calculator Node."""

    metrics: dict[str, str | float | int | dict[str, float | list[float]]] = Field(
        ..., description="Calculated valuation metrics"
    )
