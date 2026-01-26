from typing import Literal

from pydantic import BaseModel


class IntentExtractionSuccess(BaseModel):
    """Schema for successful ticker resolution."""

    kind: Literal["success"] = "success"
    resolved_ticker: str
    company_profile: dict
    status: Literal["resolved"] = "resolved"


class IntentExtractionError(BaseModel):
    """Schema for intentional extraction failures."""

    kind: Literal["error"] = "error"
    message: str


# Composite type for the adapter/mapper validation
IntentExtractionOutput = IntentExtractionSuccess | IntentExtractionError
