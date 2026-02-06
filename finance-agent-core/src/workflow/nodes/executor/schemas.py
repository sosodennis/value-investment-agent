from pydantic import BaseModel, Field


class ExecutorPreview(BaseModel):
    """UI renderable preview for Executor Agent."""

    model_type: str = Field(..., description="Type of the valuation model")
    param_count: int = Field(..., description="Number of parameters extracted")
    status: str = Field(..., description="Extraction status")
