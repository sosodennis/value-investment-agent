"""
LLM interpretation adapter for technical analysis.

Deterministic semantic decision rules are owned by domain policies.
This module only translates semantic tags into natural-language narration.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)

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
    tags_dict: JSONObject,
    ticker: str,
    backtest_context: str = "",
    wfa_context: str = "",
) -> str:
    risk_level = str(tags_dict.get("risk_level", "medium"))
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

        evidence_items = tags_dict.get("evidence_list")
        evidence_str = (
            " | ".join(str(item) for item in evidence_items)
            if isinstance(evidence_items, list) and evidence_items
            else "No specific confluence detected."
        )
        response = await chain.ainvoke(
            {
                "ticker": ticker,
                "tags": tags_dict.get("tags", []),
                "direction": tags_dict.get("direction", "NEUTRAL"),
                "risk_level": risk_level,
                "z_score": tags_dict.get("z_score", 0.0),
                "evidence": evidence_str,
                "backtest_context": backtest_context,
                "wfa_context": wfa_context,
            }
        )

        interpretation = str(response.content).strip()
        logger.info("✅ Generated interpretation: %s...", interpretation)
        return interpretation
    except Exception as exc:
        logger.error("❌ LLM interpretation failed: %s", exc)
        z_score = tags_dict.get("z_score", "N/A")
        return f"Technical analysis complete. Z-Score: {z_score}, Risk: {risk_level}"
