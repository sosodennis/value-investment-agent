from typing import Literal

from pydantic import BaseModel

from .structures import TechnicalSignal


class TechnicalAnalysisSuccess(TechnicalSignal):
    """Successful technical analysis result with discriminator."""

    kind: Literal["success"] = "success"


class TechnicalAnalysisError(BaseModel):
    """Failure schema for technical analysis."""

    kind: Literal["error"] = "error"
    message: str


TechnicalAnalysisResult = TechnicalAnalysisSuccess | TechnicalAnalysisError
