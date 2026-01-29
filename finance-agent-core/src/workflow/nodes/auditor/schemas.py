from typing import Literal

from pydantic import BaseModel, Field


class AuditorPreview(BaseModel):
    """UI renderable preview for Auditor Agent."""

    passed: bool = Field(..., description="Whether the audit passed")
    finding_count: int = Field(..., description="Number of findings")
    status: str = Field(..., description="Audit status")


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
