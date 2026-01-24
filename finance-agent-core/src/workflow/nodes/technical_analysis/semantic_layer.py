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

    def assemble(
        self,
        z_score: float,
        optimal_d: float,
        bollinger_data: dict,
        stat_strength_data: dict,
        macd_data: dict,
        obv_data: dict,
    ) -> dict:
        tags = []
        evidence_text = []

        # 1. 獲取 CDF 值僅用於 "敘事" (Display/Narrative)，不用於 "邏輯" (Logic)
        # 這樣避免了拿 "攝氏度" 和 "華氏度" 同時做判斷的邏輯混亂
        cdf_val = stat_strength_data.get("value", 50.0)

        # --- 1. Base Physical State ---
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

        # --- 2. Memory Strength ---
        mem_strength = MemoryStrength.BALANCED
        if optimal_d < 0.3:
            mem_strength = MemoryStrength.STRUCTURALLY_STABLE
            tags.append("STRUCTURE_ROBUST")
        elif optimal_d > 0.6:
            mem_strength = MemoryStrength.FRAGILE
            tags.append("STRUCTURE_FRAGILE")

        # --- 3. Confluence Detection (Cleaned Logic) ---

        # Scenario A: Perfect Storm (Short)
        # Logic: Extreme deviation + Breakout
        if (z_score > 2.0) and (bollinger_data["state"] == "BREAKOUT_UPPER"):
            tags.append("SETUP_PERFECT_STORM_SHORT")
            risk = RiskLevel.CRITICAL
            # Narrative: Use CDF here to make it sound professional
            evidence_text.append(
                f"CRITICAL: Statistical anomaly confirmed (Z={z_score:.1f}, Prob>{cdf_val:.1f}%) with volatility breakout."
            )

        # Scenario B: Perfect Storm (Long)
        elif (z_score < -2.0) and (bollinger_data["state"] == "BREAKOUT_LOWER"):
            tags.append("SETUP_PERFECT_STORM_LONG")
            risk = RiskLevel.CRITICAL
            evidence_text.append(
                f"CRITICAL: Price structure implies imminent mean reversion (Z={z_score:.1f}, Prob<{cdf_val:.1f}%)."
            )

        # Scenario C: Healthy Momentum (Trend Continuation)
        # Logic: Strong trend (Z > 1) BUT NOT Extreme (Z < 2) AND MACD supports it
        # [Fix] Removed the contradictory cdf_val check
        elif (1.0 < z_score < 2.0) and (
            macd_data["momentum_state"] == "BULLISH_EXPANDING"
        ):
            tags.append("SETUP_HEALTHY_MOMENTUM")
            evidence_text.append(
                f"Trend is supported by expanding memory momentum (Prob: {cdf_val:.1f}%) without statistical overheating."
            )

        # Scenario D: Warning (Overheating without breakout)
        # Logic: Z is getting high (e.g., > 1.5) but strictly NOT yet extreme (> 2.0)
        # This captures the "Early Warning" zone
        elif 1.5 < z_score < 2.0:
            tags.append("WARNING_INTERNAL_PRESSURE")
            evidence_text.append(
                f"Internal structure is heating up (Prob: {cdf_val:.1f}%) approaching statistical limits."
            )

        elif -2.0 < z_score < -1.5:
            tags.append("WARNING_INTERNAL_WEAKNESS")
            evidence_text.append(
                f"Internal structure is weakening (Prob: {cdf_val:.1f}%) approaching statistical limits."
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
            statistical_strength=float(round(cdf_val, 2)),  # [Change] Use CDF
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


# System prompt for LLM interpretation (General Investor Version)
INTERPRETATION_SYSTEM_PROMPT = """You are a helpful financial investment assistant. Your goal is to explain complex technical analysis data to an everyday investor who has basic financial knowledge but is NOT a quant.

**Strict Guidelines for Tone and Style:**
1. **Simple & Clear**: Avoid jargon like "mean reversion," "heteroscedasticity," or "overfitting" unless you explain them simply immediately after.
2. **Analogy-Driven**: Use metaphors (e.g., "The price is like a stretched rubber band" instead of "Statistical Anomaly").
3. **Action-Oriented**: Focus on "What does this mean for my money?" rather than the math behind it.
4. **Honest about Risks**: If the Backtest/WFA data is bad (negative WFE or Sharpe), clearly say "History suggests this strategy is risky/unreliable," don't hide behind numbers.

**Output Structure:**
1. **The Vibe (Market Sentiment)**: One sentence summary (e.g., "The stock is rising, but looks dangerous.").
2. **The Good**: What is working well? (Volume, Trend).
3. **The Bad**: What are the risks? (Overheating, Unstable history).
4. **The Bottom Line**: A clear, cautious conclusion.

Output limit: Max 200 words."""

INTERPRETATION_USER_TEMPLATE = """Asset: {ticker}
Current State Tags: {tags}
Direction: {direction}
Risk Level: {risk_level}
Z-Score: {z_score}
Evidence: {evidence}
{backtest_context}
{wfa_context}

Generate a brief, professional technical analysis report."""


async def generate_interpretation(
    tags_dict: dict, ticker: str, backtest_context: str = "", wfa_context: str = ""
) -> str:
    """
    Generate LLM interpretation from semantic tags.

    Args:
        tags_dict: Dictionary from SemanticAssembler.assemble()
        ticker: Stock ticker symbol
        backtest_context: Optional backtest verification string
        wfa_context: Optional Walk-Forward Analysis robustness string

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
                "backtest_context": backtest_context,
                "wfa_context": wfa_context,  # Add WFA robustness verification
            }
        )

        interpretation = response.content.strip()
        logger.info(f"✅ Generated interpretation: {interpretation}...")
        return interpretation

    except Exception as e:
        logger.error(f"❌ LLM interpretation failed: {e}")
        return f"Technical analysis complete. Z-Score: {tags_dict['z_score']}, Risk: {tags_dict['risk_level'].value}"
