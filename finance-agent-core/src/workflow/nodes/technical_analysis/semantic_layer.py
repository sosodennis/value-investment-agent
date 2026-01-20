"""
Semantic translation layer: deterministic tags + LLM interpretation.

Converts numerical FracDiff metrics into semantic tags and natural language.
"""

import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.utils.logger import get_logger

from .structures import (
    ConfluenceEvidence,
    MemoryStrength,
    RiskLevel,
    StatisticalState,
)

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


class SemanticAssembler:
    """
    Transforms multi-dimensional mathematical indicators into semantic tags.
    This is the core logic layer of the TA Agent.
    """

    def __init__(self):
        # Default thresholds (fallback if dynamic calculation fails)
        self.DEFAULT_THRESHOLDS = {
            "extreme_high": 95.0,
            "high": 80.0,
            "low": 20.0,
            "extreme_low": 5.0,
        }
        # Legacy constants for backward compatibility
        self.RSI_EXTREME_HIGH = 95.0
        self.RSI_HIGH = 80.0
        self.RSI_LOW = 20.0
        self.RSI_EXTREME_LOW = 5.0
        self.Z_CRITICAL = 2.5

    def assemble(
        self,
        z_score: float,
        optimal_d: float,
        bollinger_data: dict,
        rsi_data: dict,  # [Change] Type hint changed to dict
        macd_data: dict,
        obv_data: dict,
    ) -> dict:
        tags = []
        evidence_text = []  # Human-readable evidence chain

        # [Logic Update] Extract RSI value and thresholds dynamically
        rsi_val = rsi_data.get("value", 50.0)
        thresh = rsi_data.get("thresholds", self.DEFAULT_THRESHOLDS)

        # --- 1. Base Physical State (Z-Score) ---
        abs_z = abs(z_score)
        stat_state = StatisticalState.EQUILIBRIUM
        risk = RiskLevel.LOW

        if abs_z < 1.0:
            tags.append("MARKET_NOISE")
        elif 1.0 <= abs_z < 2.0:
            stat_state = StatisticalState.DEVIATING
            risk = RiskLevel.MEDIUM
            tags.append("TREND_ACTIVE")
        elif abs_z >= 2.0:
            stat_state = StatisticalState.STATISTICAL_ANOMALY
            risk = RiskLevel.CRITICAL
            tags.append("STATISTICAL_EXTREME")

        # --- 2. Memory Strength (d value) ---
        mem_strength = MemoryStrength.BALANCED
        if optimal_d < 0.3:
            mem_strength = MemoryStrength.STRUCTURALLY_STABLE
            tags.append("STRUCTURE_ROBUST")
        elif optimal_d > 0.6:
            mem_strength = MemoryStrength.FRAGILE
            tags.append("STRUCTURE_FRAGILE")

        # --- 3. Confluence Detection (The Core Logic) ---

        # Scenario A: Perfect Storm (Short) - High price + Breakout + RSI Top
        if (
            (z_score > 2.0)
            and (bollinger_data["state"] == "BREAKOUT_UPPER")
            and (rsi_val > thresh["high"])  # [Change] Use dynamic threshold
        ):
            tags.append("SETUP_PERFECT_STORM_SHORT")
            risk = RiskLevel.CRITICAL
            evidence_text.append(
                "CRITICAL: Statistical anomaly confirmed by volatility breakout and momentum exhaustion."
            )

        # Scenario B: Perfect Storm (Long) - Low price + Breakdown + RSI Bottom
        elif (
            (z_score < -2.0)
            and (bollinger_data["state"] == "BREAKOUT_LOWER")
            and (rsi_val < thresh["low"])  # [Change] Use dynamic threshold
        ):
            tags.append("SETUP_PERFECT_STORM_LONG")
            risk = RiskLevel.CRITICAL
            evidence_text.append(
                "CRITICAL: Price structure implies imminent mean reversion bounce."
            )

        # Scenario C: Healthy Momentum (Trend Continuation)
        elif (
            (z_score > 1.0)
            and (z_score < 2.5)
            and (rsi_val < thresh["high"])  # [Change] Use dynamic threshold
            and (macd_data["momentum_state"] == "BULLISH_EXPANDING")
        ):
            tags.append("SETUP_HEALTHY_MOMENTUM")
            evidence_text.append(
                "Trend is supported by expanding memory momentum without overheating."
            )

        # Scenario D: Warning (RSI Extreme but price not confirmed)
        elif (rsi_val > thresh["extreme_high"]) and (
            abs_z < 2.0
        ):  # [Change] Use dynamic threshold
            tags.append("WARNING_INTERNAL_OVERHEATING")
            evidence_text.append(
                f"Internal structure is overheated (RSI: {rsi_val:.1f}) despite price staying within bounds."
            )

        # --- 4. Volume-Price Relationship Analysis (The Lie Detector) ---
        vp_tags = []
        obv_z = obv_data["fd_obv_z"]

        # Volume Confirmed Up (Healthy)
        if (z_score > 0.5) and (obv_z > 0.5):
            vp_tags.append("VOLUME_CONFIRMED_UP")
            evidence_text.append(
                "Price rise is supported by strong volume accumulation (healthy trend)."
            )

        # Top Divergence (Price rising but smart money exiting) - CRITICAL WARNING
        elif (z_score > 1.5) and (obv_z < -0.5):
            vp_tags.append("DIVERGENCE_PRICE_UP_VOL_DOWN")
            tags.append("SMART_MONEY_EXITING")
            evidence_text.append(
                "WARNING: Price is rising but FD-OBV indicates distribution (Smart Money Exit)."
            )
            # Force upgrade risk level
            if risk != RiskLevel.CRITICAL:
                risk = RiskLevel.MEDIUM

        # Bottom Divergence (Price falling but hidden accumulation) - OPPORTUNITY
        elif (z_score < -1.5) and (obv_z > 0.5):
            vp_tags.append("DIVERGENCE_PRICE_DOWN_VOL_UP")
            tags.append("SMART_MONEY_ENTERING")
            evidence_text.append(
                "OPPORTUNITY: Price is falling but FD-OBV indicates hidden accumulation."
            )

        # Capitulation Event (Price crash + Volume crash)
        elif (z_score < -2.0) and (obv_z < -2.0):
            tags.append("CAPITULATION_EVENT")
            evidence_text.append(
                "Market is undergoing a capitulation event (High volume sell-off)."
            )

        # Merge volume-price tags
        tags.extend(vp_tags)

        # --- 4.5 Conflict Resolution (Reframing Logic) ---
        # Principle: Volume (truth) overrides Price (appearance)
        # Rather than deleting tags, we reframe conflicts as specific market patterns

        # Determine direction first to avoid undefined variable in Pattern B
        # [Fix] Don't use 0.0 as threshold. Use 0.5 to prevent flickering.
        if z_score > 0.5:
            direction = "BULLISH_EXTENSION"
        elif z_score < -0.5:
            direction = "BEARISH_EXTENSION"
        else:
            direction = "NEUTRAL_CONSOLIDATION"

        # Pattern A: Bull Trap
        # Condition: Price looks healthy but capital is flowing out
        if ("SMART_MONEY_EXITING" in tags) and ("SETUP_HEALTHY_MOMENTUM" in tags):
            # 1. Remove misleading positive tag
            tags.remove("SETUP_HEALTHY_MOMENTUM")

            # 2. Add precise pattern tag
            tags.append("PATTERN_BULL_TRAP")

            # 3. Provide explanatory evidence for LLM (force bearish interpretation)
            evidence_text.append(
                "CRITICAL OVERRIDE: Price action suggests strength, but significant capital outflows verify this is a BULL TRAP."
            )

            # 4. Force upgrade risk (traps are more dangerous than simple declines)
            risk = RiskLevel.CRITICAL

        # Pattern B: Bear Trap
        # Condition: Price is falling but capital is entering (smart money catching the knife)
        if ("SMART_MONEY_ENTERING" in tags) and (direction == "BEARISH_EXTENSION"):
            # We don't remove BEARISH_EXTENSION because price is indeed falling
            # But we add a reversal warning
            tags.append("PATTERN_BEAR_TRAP")

            evidence_text.append(
                "OPPORTUNITY OVERRIDE: Price weakness is not supported by volume; Smart money is absorbing the selling (Accumulation)."
            )

            # 5. Downgrade risk (though falling, this may be a good entry point)
            if risk == RiskLevel.CRITICAL:
                risk = RiskLevel.MEDIUM

        # --- 5. Generate Result with Dead Zone ---
        # Note: direction already calculated above

        # Construct new data structure
        confluence = ConfluenceEvidence(
            bollinger_state=bollinger_data["state"],
            rsi_score=float(round(rsi_val, 2)),  # [Change] Use rsi_val
            macd_momentum=macd_data["momentum_state"],
            obv_state=obv_data["state"],
        )

        return {
            "tags": tags,
            "direction": direction,
            "risk_level": risk,
            "memory_strength": mem_strength,
            "statistical_state": stat_state,
            "z_score": float(round(z_score, 2)),
            "confluence": confluence,
            "evidence_list": evidence_text,
        }


# Global assembler instance
assembler = SemanticAssembler()


# System prompt for LLM interpretation
INTERPRETATION_SYSTEM_PROMPT = """You are an institutional-grade technical analysis strategist (Quant Strategist).

Your role is to translate statistical state tags into professional investment insights.

**Strict Rules:**
1. **Fact-Based**: Only interpret the provided tags and evidence. Do not invent trends or data.
2. **Precise Terminology**:
   - MEMORY_STRUCTURALLY_STABLE → "The asset exhibits strong historical path dependency; trends are resilient to noise"
   - MEMORY_FRAGILE → "The asset's price behavior is highly sensitive to short-term noise; trends are unstable"
   - STATE_STATISTICAL_ANOMALY → "Current price has deviated significantly from its long-term memory equilibrium (rare event)"
3. **Risk-Oriented**: If Risk Level is CRITICAL, use strong warning language emphasizing "statistical mean reversion pressure"
4. **Evidence-Driven**: Prioritize the evidence list. Use it to construct your narrative.
5. **No Hallucination**: Do not mention any technical indicators unless explicitly provided in the evidence.

Output a concise professional analysis (max 150 words)."""

INTERPRETATION_USER_TEMPLATE = """Asset: {ticker}
Current State Tags: {tags}
Direction: {direction}
Risk Level: {risk_level}
Z-Score: {z_score}
Evidence: {evidence}

Generate a brief, professional technical analysis report."""


async def generate_interpretation(tags_dict: dict, ticker: str) -> str:
    """
    Generate LLM interpretation from semantic tags.

    Args:
        tags_dict: Dictionary from SemanticAssembler.assemble()
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

        # Format evidence list
        evidence_str = (
            " | ".join(tags_dict.get("evidence_list", []))
            if tags_dict.get("evidence_list")
            else "No specific confluence detected."
        )

        response = await chain.ainvoke(
            {
                "ticker": ticker,
                "tags": tags_dict["tags"],
                "direction": tags_dict["direction"],
                "risk_level": tags_dict["risk_level"].value,
                "z_score": tags_dict["z_score"],
                "evidence": evidence_str,
            }
        )

        interpretation = response.content.strip()
        logger.info(f"✅ Generated interpretation: {interpretation}...")
        return interpretation

    except Exception as e:
        logger.error(f"❌ LLM interpretation failed: {e}")
        return f"Technical analysis complete. Z-Score: {tags_dict['z_score']}, Risk: {tags_dict['risk_level'].value}"
