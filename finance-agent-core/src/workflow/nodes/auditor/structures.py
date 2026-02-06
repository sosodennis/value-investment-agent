from pydantic import BaseModel, Field


class AuditOutput(BaseModel):
    """Output from the Auditor Node."""

    passed: bool = Field(..., description="Whether the audit passed")
    messages: list[str] = Field(
        default_factory=list, description="Audit feedback messages"
    )
