from typing import Literal

from pydantic import BaseModel

from .structures import NewsResearchOutput


class FinancialNewsSuccess(NewsResearchOutput):
    """Successful news research result with discriminator."""

    kind: Literal["success"] = "success"


class FinancialNewsError(BaseModel):
    """Failure schema for news research."""

    kind: Literal["error"] = "error"
    message: str


FinancialNewsResult = FinancialNewsSuccess | FinancialNewsError
