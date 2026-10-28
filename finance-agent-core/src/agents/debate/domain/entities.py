from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.artifacts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    XBRLProvenance,
)

# 定義風險屬性枚舉
RiskProfileType = Literal["DEFENSIVE_VALUE", "GROWTH_TECH", "SPECULATIVE_CRYPTO_BIO"]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probability: float = Field(ge=0, le=100)
    outcome_description: str = Field(..., description="What happens in this scenario?")
    price_implication: Literal["SURGE", "MODERATE_UP", "FLAT", "MODERATE_DOWN", "CRASH"]


class ScenarioAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bull_case: Scenario
    bear_case: Scenario
    base_case: Scenario


class DebateVerdictDraft(BaseModel):
    """LLM-owned fields; deterministic verdict metrics are added downstream."""

    model_config = ConfigDict(extra="forbid")

    scenario_analysis: ScenarioAnalysis
    risk_profile: RiskProfileType
    winning_thesis: str = Field(min_length=1)
    primary_catalyst: str = Field(min_length=1)
    primary_risk: str = Field(min_length=1)
    supporting_factors: list[str]


# --- Ground Truth Facts ---

SourceType = Literal["financials", "news", "technicals", "valuation"]
SourceWeight = Literal["HIGH", "MEDIUM", "LOW"]


class EvidenceFact(BaseModel):
    """
    Ground truth fact used in the debate.
    Every fact is traceable back to its source provenance.
    """

    fact_id: str = Field(..., description="Stable ID, e.g. F001, N001, T001")
    source_type: SourceType
    source_weight: SourceWeight

    summary: str = Field(..., description="Short factual statement")
    value: float | str | None = None
    units: str | None = None
    period: str | None = None

    # Link to the original provenance from the analysis nodes
    provenance: XBRLProvenance | ComputedProvenance | ManualProvenance


class FactBundle(BaseModel):
    """
    A collection of facts extracted for a specific debate session.
    """

    ticker: str
    facts: list[EvidenceFact]
    facts_hash: str
    generated_at: str
