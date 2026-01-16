from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["LONG", "SHORT", "NEUTRAL"]


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

    winning_thesis: str
    primary_catalyst: str
    primary_risk: str
    supporting_factors: list[str]
    debate_rounds: int = Field(
        default=0, description="Number of debate rounds performed"
    )
