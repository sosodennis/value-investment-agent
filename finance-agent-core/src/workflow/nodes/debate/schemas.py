from enum import Enum

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    CATASTROPHIC = "CATASTROPHIC"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RiskFactor(BaseModel):
    description: str = Field(..., description="Specific description of the risk")
    severity: SeverityLevel = Field(..., description="Potential impact on the position")
    probability: float = Field(..., description="Estimated probability (0.0 to 1.0)")


class DebateConclusion(BaseModel):
    """
    Final structured output from the Debate Sub-Agent.
    Enforces 'Signal Collapse' for clear decision making.
    """

    # Core Decision Layer (Singular - for Signal Collapse)
    winning_thesis: str = Field(
        ..., description="The single, synthesized narrative explaining the conviction."
    )
    primary_catalyst: str = Field(
        ..., description="The specific upcoming event that will validate the thesis."
    )
    primary_risk: str = Field(
        ..., description="The single most dangerous failure-mode/stop-loss criteria."
    )

    # Signal metrics
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="0.0 to 1.0 (Connects text to math)"
    )
    direction: Direction = Field(..., description="The recommended action direction")

    # Secondary Context Layer (List - for Human Audit)
    supporting_factors: list[str] = Field(
        default_factory=list, description="Secondary arguments that support the thesis."
    )

    # Audit Trace
    debate_rounds: int = Field(
        default=0, description="Number of debate rounds performed"
    )
