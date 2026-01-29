import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    """
    Standardized event protocol for FinGraph Agent.

    This is the única truth (Source of Truth) for all events sent to the frontend.
    It decouples frontend from internal LangGraph node names and internal state shapes.
    """

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description="Unique event identifier"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Event occurrence time"
    )
    thread_id: str = Field(..., description="Conversation thread ID")
    run_id: str = Field(
        default="", description="Optional execution run ID for tracking"
    )
    seq_id: int = Field(
        ..., description="Logical clock sequence ID for ordering and deduplication"
    )

    # Event Type Discriminator
    type: Literal[
        "lifecycle.status",  # Overall agent state (started, completed, failed)
        "content.delta",  # LLM token/content streaming
        "state.update",  # Business data updates (e.g. financial reports ready)
        "interrupt.request",  # Waiting for human-in-the-loop input
        "agent.status",  # Status update for a specific sub-agent (running, done, etc.)
        "error",  # System or execution error
    ]

    # Source metadata (Decoupled from internal node names)
    source: str = Field(
        ..., description="High-level component or agent name (e.g. 'FinancialAnalyst')"
    )

    # Event Data Payload
    data: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Payload containing event-specific data. "
            "For 'state.update' events, contains AgentOutputArtifact fields: "
            "{summary: str, preview: dict | None, reference: ArtifactReference | None}"
        ),
    )

    # Optional metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional tracking metadata"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
