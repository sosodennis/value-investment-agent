from pydantic import BaseModel, Field

from src.agents.fundamental.domain.valuation.parameterization.types import (
    TraceInput,
)


class BaseValuationParams(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol")
    rationale: str = Field(
        ..., description="Reasoning behind the parameter assumptions, with citations."
    )
    trace_inputs: dict[str, TraceInput] = Field(
        default_factory=dict, description="Optional TraceableField inputs"
    )
