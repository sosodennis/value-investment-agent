from typing import Any

from pydantic import BaseModel, Field


class ExtractionOutput(BaseModel):
    """
    Output from the Executor Node.
    Wraps the extracted parameters.
    """

    # Using Dict[str, Any] as a fallback for varying schema types until specific models are unified.
    # Ideally this should be Union[SaasParams, BankParams, etc.]
    params: dict[str, Any] = Field(
        ..., description="Extracted validation parameters complying with model schema"
    )
