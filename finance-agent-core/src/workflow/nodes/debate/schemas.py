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


class PriceImplication(str, Enum):
    SURGE = "SURGE"  # > 20%
    MODERATE_UP = "MODERATE_UP"  # 5-20%
    FLAT = "FLAT"  # -5% to +5%
    MODERATE_DOWN = "MODERATE_DOWN"  # -5% to -20%
    CRASH = "CRASH"  # < -20%


class Scenario(BaseModel):
    probability: float = Field(..., ge=0.0, le=1.0, description="0.0 to 1.0")
    outcome_description: str = Field(..., description="What happens in this scenario?")
    price_implication: PriceImplication = Field(
        ..., description="Implied price movement"
    )


class DebateConclusion(BaseModel):
    """
    V4.0 Bayesian Conclusion.
    Enforces probabilistic thinking over binary decisions.
    """

    # Bayesian Core
    scenario_analysis: dict[str, Scenario] = Field(
        ..., description="Keys: bull_case, bear_case, base_case"
    )

    # Decision Layer
    final_verdict: Direction = Field(
        ..., description="The recommended action direction"
    )
    kelly_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Adjusted confidence based on EV analysis"
    )

    # Narrative Context
    winning_thesis: str = Field(
        ..., description="The single, synthesized narrative explaining the conviction."
    )
    primary_catalyst: str = Field(
        ..., description="The specific upcoming event that will validate the thesis."
    )
    primary_risk: str = Field(
        ..., description="The single most dangerous failure-mode/stop-loss criteria."
    )

    # Secondary Context Layer
    supporting_factors: list[str] = Field(
        default_factory=list, description="Secondary arguments that support the thesis."
    )

    # Audit Trace
    debate_rounds: int = Field(
        default=0, description="Number of debate rounds performed"
    )
