from pydantic import BaseModel, Field


class DebatePreview(BaseModel):
    """Preview data for Debate UI (<1KB)"""

    verdict_display: str = Field(..., description="e.g. '📈 STRONG_LONG (RR: 2.1x)'")
    thesis_display: str = Field(
        ..., description="1-sentence summary of the investment case"
    )
    catalyst_display: str = Field(..., description="Major price driver")
    risk_display: str = Field(..., description="Major risk factor")
    debate_rounds_display: str = Field(
        ..., description="e.g. 'Completed 3 rounds of adversarial debate'"
    )
