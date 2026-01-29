from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecutorPreview(BaseModel):
    """UI renderable preview for Executor Agent."""

    model_type: str = Field(..., description="Type of the valuation model")
    param_count: int = Field(..., description="Number of parameters extracted")
    status: str = Field(..., description="Extraction status")


class ExecutorSuccess(BaseModel):
    """Successful parameter extraction result."""

    kind: Literal["success"] = "success"
    params: dict[str, Any]
    model_type: str


class ExecutorError(BaseModel):
    """Failure schema for executor."""

    kind: Literal["error"] = "error"
    message: str


ExecutorResult = ExecutorSuccess | ExecutorError
