from pydantic import BaseModel, Field

from src.shared.kernel.traceable import TraceableField

TraceInput = TraceableField[float] | TraceableField[list[float]]


class BaseValuationParams(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol")
    rationale: str = Field(
        ..., description="Reasoning behind the parameter assumptions, with citations."
    )
    trace_inputs: dict[str, TraceInput] = Field(
        default_factory=dict, description="Optional TraceableField inputs"
    )
