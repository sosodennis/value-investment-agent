from typing import Literal

from pydantic import BaseModel


class AuditorSuccess(BaseModel):
    """Successful audit result."""

    kind: Literal["success"] = "success"
    passed: bool
    messages: list[str]


class AuditorError(BaseModel):
    """Failure schema for auditor."""

    kind: Literal["error"] = "error"
    message: str


AuditorResult = AuditorSuccess | AuditorError
