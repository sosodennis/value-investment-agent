import json
import os
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...state import AgentState
from .prompts import (
    BEAR_AGENT_SYSTEM_PROMPT,
    BEAR_R1_ADVERSARIAL,
    BEAR_R2_ADVERSARIAL,
    BULL_AGENT_SYSTEM_PROMPT,
    BULL_R1_ADVERSARIAL,
    BULL_R2_ADVERSARIAL,
    MODERATOR_SYSTEM_PROMPT,
    VERDICT_PROMPT,
)
from .schemas import DebateConclusion
from .utils import calculate_kelly_and_verdict

# --- LLM Shared Config ---
DEFAULT_MODEL = "mistralai/devstral-2512:free"
MAX_CHAR_REPORTS = 50000
MAX_CHAR_HISTORY = 32000


def _compress_reports(reports: dict, max_chars: int = MAX_CHAR_REPORTS) -> str:
    """Compress analyst reports to fit context window."""
    if not reports:
        return "{}"

    # Try indent=1 first
    compressed = json.dumps(reports, indent=1, default=str)
    if len(compressed) <= max_chars:
        return compressed

    # If still too big, try no indent
    compressed = json.dumps(reports, separators=(",", ":"), default=str)
    if len(compressed) <= max_chars:
        return compressed

    # Hard truncation with warning
    print(f"⚠️ Truncating analyst reports: {len(compressed)} -> {max_chars}", flush=True)
    return compressed[:max_chars] + "\n\n[... TRUNCATED DUE TO TOKEN LIMITS ...]"


def _get_trimmed_history(history: list, max_chars: int = MAX_CHAR_HISTORY) -> list:
    """Get the most recent messages that fit within the character budget."""
    if not history:
        return []

    trimmed = []
    current_chars = 0

    # Iterate backwards through history
    for msg in reversed(history):
        msg_content = str(msg.content)
        if current_chars + len(msg_content) > max_chars:
            break
        trimmed.insert(0, msg)
        current_chars += len(msg_content)

    return trimmed


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0):
    """Factory for ChatOpenAI instance with OpenRouter support."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    base_url = "https://openrouter.ai/api/v1"

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = "https://api.openai.com/v1"

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key,
        base_url=base_url,
    )


def debate_aggregator_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 1] Aggregator Node
    Consolidates data from News Research and Fundamental Analysis into
    a single 'analyst_reports' dictionary for the debate agents to consume.

    Includes source reliability weighting to guide agents on evidence quality.
    """
    print("--- Debate: Aggregating ground truth data ---", flush=True)

    # Consolidate news and financials with reliability metadata
    reports = {
        "financials": {
            "data": state.financial_reports,
            "source_weight": "HIGH",
            "rationale": "Primary source: SEC XBRL filings (audited, regulatory-grade data)",
        },
        "news": {
            "data": state.financial_news_output,
            "source_weight": "MEDIUM",
            "rationale": "Secondary source: Curated financial news (editorial bias possible)",
        },
        "ticker": state.resolved_ticker or state.ticker,
    }

    return {
        "analyst_reports": reports,
        "current_node": "debate_aggregator",
        "node_statuses": {"debate_aggregator": "done", "bull": "running"},
    }


async def bull_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bull Agent (The Growth Hunter)
    Role: Focus on catalysts, growth potential, and bullish news.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Bull Agent Node (Round {round_num}) ---", flush=True)

    try:
        llm = get_llm()

        # Optimize context
        compressed_reports = _compress_reports(state.analyst_reports)
        trimmed_history = _get_trimmed_history(state.debate_history)

        # Dynamic Instruction Check
        adversarial_rule = (
            BULL_R1_ADVERSARIAL if round_num == 1 else BULL_R2_ADVERSARIAL
        )

        system_content = BULL_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )

        messages = [SystemMessage(content=system_content)] + trimmed_history
        response = await llm.ainvoke(messages)

        print(
            f"--- Debate: Bull Agent '{ticker}' Arg (Round {round_num}):\n{response.content[:200]}...",
            flush=True,
        )

        return {
            "debate_history": [
                AIMessage(content=response.content, name="GrowthHunter")
            ],
            "bull_thesis": response.content,
            "current_node": "bull",
            "node_statuses": {"bull": "done", "bear": "running"},
        }
    except Exception as e:
        print(f"❌ Error in Bull Node: {str(e)}", flush=True)
        fallback_msg = (
            f"Bull Analysis Error: {str(e)[:100]}. Proceeding with limited data."
        )
        return {
            "debate_history": [AIMessage(content=fallback_msg, name="GrowthHunter")],
            "bull_thesis": fallback_msg,
            "current_node": "bull",
            "node_statuses": {"bull": "error", "bear": "running"},
        }


async def bear_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bear Agent (The Forensic Accountant)
    Role: Focus on risks, red flags, and challenging the Bull's narrative.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Bear Agent Node (Round {round_num}) ---", flush=True)

    try:
        llm = get_llm()

        # Optimize context
        compressed_reports = _compress_reports(state.analyst_reports)
        trimmed_history = _get_trimmed_history(state.debate_history)

        # Dynamic Instruction Check
        adversarial_rule = (
            BEAR_R1_ADVERSARIAL if round_num == 1 else BEAR_R2_ADVERSARIAL
        )

        system_content = BEAR_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )

        messages = [SystemMessage(content=system_content)] + trimmed_history
        response = await llm.ainvoke(messages)

        print(
            f"--- Debate: Bear Agent '{ticker}' Arg (Round {round_num}):\n{response.content[:200]}...",
            flush=True,
        )

        return {
            "debate_history": [
                AIMessage(content=response.content, name="ForensicAccountant")
            ],
            "bear_thesis": response.content,
            "current_node": "bear",
            "node_statuses": {"bear": "done", "moderator": "running"},
        }
    except Exception as e:
        print(f"❌ Error in Bear Node: {str(e)}", flush=True)
        fallback_msg = (
            f"Bear Analysis Error: {str(e)[:100]}. Proceeding with limited data."
        )
        return {
            "debate_history": [
                AIMessage(content=fallback_msg, name="ForensicAccountant")
            ],
            "bear_thesis": fallback_msg,
            "current_node": "bear",
            "node_statuses": {"bear": "error", "moderator": "running"},
        }


async def moderator_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2/3] Moderator Agent (The Judge)
    Role: Decides if consensus is reached or if debate should continue/conclude.
    Also handles the final 'Verdict' synthesis in Phase 3.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Moderator Node (Round {round_num}) ---", flush=True)

    llm = get_llm()

    if round_num < 3:
        # Standard Critique/Redirect Round with Sycophancy Check
        try:
            # Check for excessive agreement (sycophancy)
            from .utils import get_sycophancy_detector

            detector = get_sycophancy_detector()
            similarity, is_sycophantic = detector.check_consensus(
                state.bull_thesis or "", state.bear_thesis or ""
            )

            print(
                f"--- Debate: Similarity Check (Round {round_num}): {similarity:.3f} "
                f"({'SYCOPHANTIC' if is_sycophantic else 'OK'}) ---",
                flush=True,
            )

            # Optimize context
            compressed_reports = _compress_reports(state.analyst_reports)
            trimmed_history = _get_trimmed_history(state.debate_history)

            system_content = MODERATOR_SYSTEM_PROMPT.format(
                ticker=ticker,
                reports=compressed_reports,
            )

            # If sycophantic, add forced re-challenge instruction
            if is_sycophantic:
                system_content += f"""

    ⚠️ SYCOPHANCY DETECTED (Similarity: {similarity:.2f})
    The Bull and Bear agents are in excessive agreement. This defeats the purpose of adversarial debate.

    MANDATORY INTERVENTION:
    1. Identify the specific point where they are agreeing.
    2. Command the NEXT agent to find AT LEAST 3 specific counter-arguments or risks that were NOT addressed.
    3. Do NOT allow generic statements. Demand data-backed objections.
    """

            messages = [SystemMessage(content=system_content)] + trimmed_history
            response = await llm.ainvoke(messages)

            print(
                f"--- Debate: Moderator critique (Round {round_num}):\n{response.content[:200]}...",
                flush=True,
            )

            return {
                "debate_history": [AIMessage(content=response.content, name="Judge")],
                "debate_current_round": round_num,
                "current_node": "moderator",
                "node_statuses": {"moderator": "done"},
            }
        except Exception as e:
            print(f"❌ Error in Moderator Node: {str(e)}", flush=True)
            return {
                "debate_history": [
                    AIMessage(content=f"Moderator Error: {str(e)[:100]}", name="Judge")
                ],
                "debate_current_round": round_num,
                "current_node": "moderator",
                "node_statuses": {"moderator": "error"},
            }
    else:
        # Final Round: Synthesis of the DebateConclusion (Bayesian V4.0)
        print("--- Debate: Final Synthesis (Verdict) ---", flush=True)

        # Optimize context for final verdict
        trimmed_history = _get_trimmed_history(
            state.debate_history, max_chars=MAX_CHAR_HISTORY * 1.5
        )

        history_text = "\n\n".join(
            [f"{msg.name or 'Agent'}: {msg.content}" for msg in trimmed_history]
        )
        verdict_system = VERDICT_PROMPT.format(ticker=ticker, history=history_text)

        # Attempt structured output - fallback to manual parse if model fails
        try:
            structured_llm = llm.with_structured_output(DebateConclusion)
            conclusion = await structured_llm.ainvoke(verdict_system)

            # Use mode='json' to handle Enums/Scenarios correctly
            conclusion_data = conclusion.model_dump(mode="json")

            # ==========================================
            # 🔥 Neuro-Symbolic Calculation Layer 🔥
            # ==========================================
            print(
                f"📊 Raw LLM Verdict: {conclusion_data.get('final_verdict')} | Intuitive Conf: {conclusion_data.get('kelly_confidence')}",
                flush=True,
            )

            # Call calculation function to get math-based metrics
            metrics = calculate_kelly_and_verdict(
                conclusion_data.get("scenario_analysis", {})
            )

            # Check if safety lock triggered (Calculated Verdict != Raw LLM Verdict)
            if (
                metrics["final_verdict"] == "NEUTRAL"
                and conclusion_data.get("final_verdict") == "LONG"
            ):
                print(
                    "⚠️ [Safety Lock] Risk detected. Overriding LONG to NEUTRAL.",
                    flush=True,
                )
                conclusion_data["winning_thesis"] = (
                    f"[SAFETY OVERRIDE] {conclusion_data.get('winning_thesis', '')}"
                )

            # Apply pure calculations to the final output
            conclusion_data.update(metrics)

            print(
                f"🧮 Calculated Verdict: {conclusion_data.get('final_verdict')} | Kelly: {conclusion_data.get('kelly_confidence')} | EV: {conclusion_data.get('expected_value')}",
                flush=True,
            )
            # ==========================================

        except Exception as e:
            print(
                f"!!! Debate: Structured output failed: {e}. Falling back to text.",
                flush=True,
            )
            # Simple fallback (could be refined more)
            conclusion_data = {
                "scenario_analysis": {
                    "bull_case": {
                        "probability": 0.33,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                    "bear_case": {
                        "probability": 0.33,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                    "base_case": {
                        "probability": 0.34,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                },
                "final_verdict": "NEUTRAL",
                "kelly_confidence": 0.0,
                "winning_thesis": "Analysis error - defaulting to safety.",
                "primary_catalyst": "N/A",
                "primary_risk": "System error during synthesis",
                "supporting_factors": [str(e)],
            }

        conclusion_data["debate_rounds"] = round_num

        print(
            f"--- Debate: Final Verdict for {ticker} ---\n{json.dumps(conclusion_data, indent=2, default=str)}",
            flush=True,
        )

        return {
            "debate_conclusion": conclusion_data,
            "debate_current_round": round_num,
            "current_node": "moderator",
            "node_statuses": {
                "debate": "done",
                "moderator": "done",
                "executor": "running",
            },
        }
