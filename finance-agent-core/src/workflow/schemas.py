from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel, Field

# Section 3: Data Structure Standards
class ValuationParameter(BaseModel):
    name: str = Field(..., description="Name of the financial parameter")
    value: float = Field(..., description="The numerical value extracted")
    source: str = Field(..., description="URL or Document Name")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence score")

class ExtractionOutput(BaseModel):
    """
    Output from the Executor Node.
    Wraps the extracted parameters.
    """
    # Using Dict[str, Any] as a fallback for varying schema types until specific models are unified.
    # Ideally this should be Union[SaasParams, BankParams, etc.]
    params: Dict[str, Any] = Field(..., description="Extracted validation parameters complying with model schema")
    
class AuditOutput(BaseModel):
    """Output from the Auditor Node."""
    passed: bool = Field(..., description="Whether the audit passed")
    messages: List[str] = Field(default_factory=list, description="Audit feedback messages")

class CalculationOutput(BaseModel):
    """Output from the Calculator Node."""
    metrics: Dict[str, Union[str, float, int, Dict[str, Union[float, List[float]]]]] = Field(..., description="Calculated valuation metrics")
