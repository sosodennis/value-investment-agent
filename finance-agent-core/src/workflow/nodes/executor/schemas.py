from typing import Any, Literal

from pydantic import BaseModel


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
