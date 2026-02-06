from pydantic import BaseModel, Field


class TechnicalAnalysisPreview(BaseModel):
    """L2 Preview data for Technical Analysis UI (<1KB)"""

    latest_price_display: str = Field(..., description="e.g. '$245.67'")
    signal_display: str = Field(..., description="e.g. '📈 BUY'")
    z_score_display: str = Field(..., description="e.g. 'Z: +2.1 (Overbought)'")
    optimal_d_display: str = Field(..., description="e.g. 'd=0.42'")
    strength_display: str = Field(..., description="e.g. 'Strength: High'")
