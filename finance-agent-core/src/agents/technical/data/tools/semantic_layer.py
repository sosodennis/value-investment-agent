"""
LLM interpretation adapter for technical analysis.

Deterministic semantic decision rules are owned by domain policies.
This module only translates semantic tags into natural-language narration.
"""

from __future__ import annotations

import logging

from src.agents.technical.domain.prompt_builder import build_interpretation_prompt_spec
from src.agents.technical.interface.prompt_renderers import (
    build_interpretation_chat_prompt,
)
from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


async def generate_interpretation(
    tags_dict: JSONObject,
    ticker: str,
    backtest_context: str = "",
    wfa_context: str = "",
) -> str:
    risk_level = str(tags_dict.get("risk_level", "medium"))
    try:
        log_event(
            logger,
            event="technical_llm_interpretation_started",
            message="technical llm interpretation started",
            fields={"ticker": ticker},
        )
        prompt_spec = build_interpretation_prompt_spec()

        prompt = build_interpretation_chat_prompt(
            system_prompt=prompt_spec.system,
            user_prompt=prompt_spec.user,
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
        log_event(
            logger,
            event="technical_llm_interpretation_completed",
            message="technical llm interpretation completed",
            fields={"ticker": ticker, "interpretation_preview": interpretation[:120]},
        )
        return interpretation
    except Exception as exc:
        log_event(
            logger,
            event="technical_llm_interpretation_failed",
            message="technical llm interpretation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_LLM_INTERPRETATION_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        z_score = tags_dict.get("z_score", "N/A")
        return f"Technical analysis complete. Z-Score: {z_score}, Risk: {risk_level}"
