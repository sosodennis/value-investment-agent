from typing import Any, Literal

from pydantic import BaseModel


class CalculatorSuccess(BaseModel):
    """Successful calculation result."""

    kind: Literal["success"] = "success"
    metrics: dict[str, Any]
    model_type: str


class CalculatorError(BaseModel):
    """Failure schema for calculator."""

    kind: Literal["error"] = "error"
    message: str


CalculatorResult = CalculatorSuccess | CalculatorError
