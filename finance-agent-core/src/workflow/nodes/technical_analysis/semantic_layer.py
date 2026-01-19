"""
Semantic translation layer: deterministic tags + LLM interpretation.

Converts numerical FracDiff metrics into semantic tags and natural language.
"""

import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.utils.logger import get_logger

from .structures import MemoryStrength, RiskLevel, StatisticalState

logger = get_logger(__name__)

# LLM Configuration
DEFAULT_MODEL = "mistralai/devstral-2512:free"


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0):
    """Get configured LLM instance."""
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        timeout=60,
        max_retries=2,
        streaming=False,
    )


def translate_to_tags(z_score: float, optimal_d: float) -> dict:
    """
    Map numerical values to semantic tags (deterministic, no LLM).

    Args:
        z_score: Z-score of FracDiff value
        optimal_d: Optimal fractional differentiation order

    Returns:
        Dictionary with tags, direction, and risk_level
    """
    tags = []

    # Memory strength classification based on d value
    if optimal_d < 0.3:
        memory_strength = MemoryStrength.STRUCTURALLY_STABLE
        tags.append("MEMORY_STRUCTURALLY_STABLE")
        tags.append("TREND_HIGH_CONFIDENCE")
    elif optimal_d > 0.6:
        memory_strength = MemoryStrength.FRAGILE
        tags.append("MEMORY_FRAGILE")
        tags.append("TREND_NOISY")
    else:
        memory_strength = MemoryStrength.BALANCED
        tags.append("MEMORY_BALANCED")

    # Statistical state classification based on Z-score
    abs_z = abs(z_score)

    if abs_z < 1.0:
        statistical_state = StatisticalState.EQUILIBRIUM
        tags.append("STATE_EQUILIBRIUM")
        risk_level = RiskLevel.LOW
    elif 1.0 <= abs_z < 2.0:
        statistical_state = StatisticalState.DEVIATING
        tags.append("STATE_DEVIATING")
        risk_level = RiskLevel.MEDIUM
    else:  # >= 2.0
        statistical_state = StatisticalState.STATISTICAL_ANOMALY
        tags.append("STATE_STATISTICAL_ANOMALY")
        tags.append("MEAN_REVERSION_IMMINENT")
        risk_level = RiskLevel.CRITICAL

    # Direction classification
    if z_score > 0:
        direction = "BULLISH_EXTENSION"
    else:
        direction = "BEARISH_EXTENSION"

    logger.info(
        f"--- TA: Semantic Tags: {tags}, Direction: {direction}, Risk: {risk_level.value} ---"
    )

    return {
        "tags": tags,
        "direction": direction,
        "risk_level": risk_level,
        "memory_strength": memory_strength,
        "statistical_state": statistical_state,
        "z_score": float(round(z_score, 2)),
    }


# System prompt for LLM interpretation
INTERPRETATION_SYSTEM_PROMPT = """You are an institutional-grade technical analysis strategist (Quant Strategist).

Your role is to translate statistical state tags into professional investment insights.

**Strict Rules:**
1. **Fact-Based**: Only interpret the provided tags. Do not invent trends or data.
2. **Precise Terminology**:
   - MEMORY_STRUCTURALLY_STABLE → "The asset exhibits strong historical path dependency; trends are resilient to noise"
   - MEMORY_FRAGILE → "The asset's price behavior is highly sensitive to short-term noise; trends are unstable"
   - STATE_STATISTICAL_ANOMALY → "Current price has deviated significantly from its long-term memory equilibrium (rare event)"
3. **Risk-Oriented**: If Risk Level is CRITICAL, use strong warning language emphasizing "statistical mean reversion pressure"
4. **No Hallucination**: Do not mention any technical indicators (MACD, RSI, etc.) unless explicitly provided

Output a concise professional analysis (max 100 words)."""

INTERPRETATION_USER_TEMPLATE = """Asset: {ticker}
Current State Tags: {tags}
Direction: {direction}
Risk Level: {risk_level}
Z-Score: {z_score}

Generate a brief, professional technical analysis report."""


async def generate_interpretation(tags_dict: dict, ticker: str) -> str:
    """
    Generate LLM interpretation from semantic tags.

    Args:
        tags_dict: Dictionary from translate_to_tags()
        ticker: Stock ticker symbol

    Returns:
        LLM-generated interpretation string
    """
    try:
        logger.info("--- TA: Generating LLM interpretation ---")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", INTERPRETATION_SYSTEM_PROMPT),
                ("human", INTERPRETATION_USER_TEMPLATE),
            ]
        )

        llm = get_llm()
        chain = prompt | llm

        response = await chain.ainvoke(
            {
                "ticker": ticker,
                "tags": tags_dict["tags"],
                "direction": tags_dict["direction"],
                "risk_level": tags_dict["risk_level"].value,
                "z_score": tags_dict["z_score"],
            }
        )

        interpretation = response.content.strip()
        logger.info(f"✅ Generated interpretation: {interpretation[:500]}...")
        return interpretation

    except Exception as e:
        logger.error(f"❌ LLM interpretation failed: {e}")
        return f"Technical analysis complete. Z-Score: {tags_dict['z_score']}, Risk: {tags_dict['risk_level'].value}"
