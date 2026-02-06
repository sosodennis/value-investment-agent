from pydantic import BaseModel, Field


class AuditorPreview(BaseModel):
    """UI renderable preview for Auditor Agent."""

    passed: bool = Field(..., description="Whether the audit passed")
    finding_count: int = Field(..., description="Number of findings")
    status: str = Field(..., description="Audit status")
