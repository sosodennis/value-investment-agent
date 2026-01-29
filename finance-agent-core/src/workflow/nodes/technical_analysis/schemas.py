from typing import Literal

from pydantic import BaseModel, Field

from .structures import TechnicalSignal


class TechnicalAnalysisPreview(BaseModel):
    """L2 Preview data for Technical Analysis UI (<1KB)"""

    latest_price_display: str = Field(..., description="e.g. '$245.67'")
    signal_display: str = Field(..., description="e.g. '📈 BUY'")
    z_score_display: str = Field(..., description="e.g. 'Z: +2.1 (Overbought)'")
    optimal_d_display: str = Field(..., description="e.g. 'd=0.42'")
    strength_display: str = Field(..., description="e.g. 'Strength: High'")


class TechnicalAnalysisSuccess(TechnicalSignal):
    """Successful technical analysis result with discriminator."""

    kind: Literal["success"] = "success"


class TechnicalAnalysisError(BaseModel):
    """Failure schema for technical analysis."""

    kind: Literal["error"] = "error"
    message: str


TechnicalAnalysisResult = TechnicalAnalysisSuccess | TechnicalAnalysisError
