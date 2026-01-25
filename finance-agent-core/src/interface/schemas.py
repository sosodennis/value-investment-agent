from typing import Any

from pydantic import BaseModel, Field


class AgentOutputArtifact(BaseModel):
    """
    Standard container for all Sub-Agent outputs.
    This structure ensures that the backend and frontend have a consistent contract,
    allowing for dynamic discovery and rendering of agent results.
    """

    summary: str = Field(..., description="Short summary for human readability")
    data: dict[str, Any] = Field(
        ..., description="Raw data required by frontend components"
    )
    # ui_schema: Optional[dict] = None  # Reserved for Server-Driven UI (Phase 2)
