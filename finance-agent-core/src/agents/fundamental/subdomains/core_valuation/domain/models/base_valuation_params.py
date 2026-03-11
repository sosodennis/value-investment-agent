from pydantic import BaseModel, Field

from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.types import (
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
