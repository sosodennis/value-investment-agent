from typing import Literal

from pydantic import BaseModel, Field

from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    XBRLProvenance,
)

Direction = Literal["STRONG_LONG", "LONG", "NEUTRAL", "AVOID", "SHORT", "STRONG_SHORT"]

# 定義風險屬性枚舉
RiskProfileType = Literal["DEFENSIVE_VALUE", "GROWTH_TECH", "SPECULATIVE_CRYPTO_BIO"]


class Scenario(BaseModel):
    # 這裡改用 score (0-100)，不再強制要求 sum=1.0
    probability: float = Field(
        ...,
        description="Likelihood Score (0-100). Independent rating of this scenario's strength.",
    )
    outcome_description: str = Field(..., description="What happens in this scenario?")
    # 使用抽象的金融邏輯，而不是具體數字
    price_implication: Literal["SURGE", "MODERATE_UP", "FLAT", "MODERATE_DOWN", "CRASH"]


class DebateConclusion(BaseModel):
    scenario_analysis: dict[str, Scenario] = Field(
        ..., description="Keys: 'bull_case', 'bear_case', 'base_case'"
    )

    # 讓 AI 判斷資產屬性
    risk_profile: RiskProfileType = Field(
        ..., description="Categorize the asset based on volatility and sector logic."
    )

    final_verdict: Direction
    kelly_confidence: float = Field(
        default=0.0, description="Leave 0.0, calculated by system."
    )
    variance: float | None = Field(
        default=0.0, description="Calculated variance of the trade."
    )

    # V2.0 Simplified Metrics
    alpha: float | None = Field(
        default=None, description="Excess return over Risk-Free Rate"
    )
    risk_free_benchmark: float | None = Field(
        default=None, description="Dynamic quarterly Risk-Free Rate used"
    )
    rr_ratio: float | None = Field(
        default=None, description="Reward/Risk Ratio (Upside / Downside)"
    )
    raw_ev: float | None = Field(default=0.0, description="Raw expected value")
    analysis_bias: str | None = Field(
        default=None, description="Qualitative bias (BULLISH/BEARISH/FLAT)"
    )
    conviction: int | None = Field(default=None, description="Confidence score (0-100)")
    model_summary: str | None = Field(
        default=None, description="Quant summary of RR and Alpha"
    )
    data_quality_warning: bool | None = Field(
        default=False, description="Flag for suspicious data quality"
    )

    winning_thesis: str = Field(
        ..., description="A concise 1-sentence summary of the core investment reason."
    )
    primary_catalyst: str = Field(
        ..., description="The most important single event that will drive price action."
    )
    primary_risk: str = Field(
        ..., description="The most critical factor that could break the thesis."
    )
    supporting_factors: list[str] = Field(
        ..., description="A list of secondary supporting facts."
    )
    debate_rounds: int = Field(
        default=0, description="Number of debate rounds performed"
    )


# --- Ground Truth Facts ---

SourceType = Literal["financials", "news", "technicals"]
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
