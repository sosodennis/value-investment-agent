import json
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.utils.logger import get_logger

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
from .utils import (
    calculate_pragmatic_verdict,
    compress_financial_data,
    compress_news_data,
)

logger = get_logger(__name__)

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
    logger.warning(f"⚠️ Truncating analyst reports: {len(compressed)} -> {max_chars}")
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


def _log_messages(messages: list, agent_name: str, round_num: int = 0):
    """Log full message content for audit/debugging."""
    log_header = f"DEBUG - PROMPT SENT TO {agent_name}"
    if round_num:
        log_header += f" (Round {round_num})"

    formatted_msg = "\n" + "=" * 50 + f"\n{log_header}\n" + "=" * 50 + "\n"
    for i, msg in enumerate(messages):
        role = (
            "System"
            if isinstance(msg, SystemMessage)
            else "Human"
            if isinstance(msg, HumanMessage)
            else "AI"
            if isinstance(msg, AIMessage)
            else "Unknown"
        )
        content = msg.content
        formatted_msg += f"[{i+1}] {role} Message:\n{content}\n" + "-" * 30 + "\n"
    formatted_msg += "=" * 50
    logger.info(formatted_msg)


def _get_last_message_from_role(history: list, role_name: str) -> str:
    """Helper to extract the last message from a specific role with fallback."""
    if not history:
        return ""
    for msg in reversed(history):
        # 優先檢查 .name 屬性
        if hasattr(msg, "name") and msg.name == role_name:
            return msg.content
        # 其次檢查 additional_kwargs (某些模型會放在這裡)
        if (
            isinstance(msg, AIMessage)
            and msg.additional_kwargs.get("name") == role_name
        ):
            return msg.content
    return ""


async def debate_aggregator_node(state: AgentState) -> dict[str, Any]:
    # Compress data before passing to debate state
    clean_financials = compress_financial_data(state.fundamental.financial_reports)
    clean_news = compress_news_data(state.financial_news.output)

    reports = {
        "financials": {
            "data": clean_financials,
            "source_weight": "HIGH",
            "rationale": "Primary source: SEC XBRL filings (audited, regulatory-grade data)",
        },
        "news": {
            "data": clean_news,
            "source_weight": "MEDIUM",
            "rationale": "Secondary source: Curated financial news (editorial bias possible)",
        },
        "ticker": state.fundamental.resolved_ticker or state.ticker,
    }

    return {
        "debate": {"analyst_reports": reports},
        "current_node": "debate_aggregator",
        "node_statuses": {"debate_aggregator": "done", "bull": "running"},
    }


async def bull_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bull Agent (The Growth Hunter)
    Role: Focus on catalysts, growth potential, and bullish news.
    """
    round_num = state.debate.current_round + 1
    ticker = state.fundamental.resolved_ticker or state.ticker
    logger.info(f"--- Debate: Bull Agent Node (Round {round_num}) ---")

    try:
        llm = get_llm()

        # Optimize context
        compressed_reports = _compress_reports(state.debate.analyst_reports)

        # Dynamic Instruction Check
        adversarial_rule = (
            BULL_R1_ADVERSARIAL if round_num == 1 else BULL_R2_ADVERSARIAL
        )

        system_content = BULL_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )

        messages = [SystemMessage(content=system_content)]

        # --- Context Sandwich Construction ---
        if round_num == 1:
            # Round 1: Keep it clean, just reports + system prompt
            pass

        else:
            # Round 2+: Construct the Sandwich

            # A. Extract Key History Elements
            my_last_arg = _get_last_message_from_role(
                state.debate.history, "GrowthHunter"
            )
            bear_last_arg = _get_last_message_from_role(
                state.debate.history, "ForensicAccountant"
            )
            judge_feedback = _get_last_message_from_role(state.debate.history, "Judge")

            # B. Self-Anchor (Consistency)
            if my_last_arg:
                messages.append(
                    AIMessage(
                        content=f"(My Previous Argument in Round 1):\n{my_last_arg}"
                    )
                )

            # C. Judge's Order (Authority)
            if judge_feedback:
                messages.append(
                    HumanMessage(
                        content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>\n"
                        f"INSTRUCTION: Address the Moderator's feedback in your response."
                    )
                )

            # D. The Target (The Enemy)
            if bear_last_arg:
                target_prompt = (
                    f"The Bear Agent has just responded.\n"
                    f"Your task is to DESTROY this specific argument:\n\n"
                    f"<opponent_argument_to_shred>\n{bear_last_arg}\n</opponent_argument_to_shred>"
                )
                messages.append(HumanMessage(content=target_prompt))

        _log_messages(messages, "BULL_AGENT", round_num)
        response = await llm.ainvoke(messages)

        logger.info(
            f"--- Debate: Bull Agent '{ticker}' Arg (Round {round_num}):\n{response.content}..."
        )

        return {
            "debate": {
                "history": [AIMessage(content=response.content, name="GrowthHunter")],
                "bull_thesis": response.content,
            },
            "current_node": "bull",
            "node_statuses": {"bull": "done", "bear": "running"},
        }
    except Exception as e:
        logger.error(f"❌ Error in Bull Node: {str(e)}")
        fallback_msg = (
            f"Bull Analysis Error: {str(e)[:100]}. Proceeding with limited data."
        )
        return {
            "debate": {
                "history": [AIMessage(content=fallback_msg, name="GrowthHunter")],
                "bull_thesis": fallback_msg,
            },
            "current_node": "bull",
            "node_statuses": {"bull": "error", "bear": "running"},
        }


async def bear_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bear Agent (The Forensic Accountant)
    Role: Focus on risks, red flags, and challenging the Bull's narrative.
    """
    round_num = state.debate.current_round + 1
    ticker = state.fundamental.resolved_ticker or state.ticker
    logger.info(f"--- Debate: Bear Agent Node (Round {round_num}) ---")

    try:
        llm = get_llm()

        # Optimize context
        compressed_reports = _compress_reports(state.debate.analyst_reports)

        # Dynamic Instruction Check
        adversarial_rule = (
            BEAR_R1_ADVERSARIAL if round_num == 1 else BEAR_R2_ADVERSARIAL
        )

        system_content = BEAR_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )

        messages = [SystemMessage(content=system_content)]

        # --- Context Sandwich Construction ---
        if round_num == 1:
            # Round 1: Keep it clean
            pass

        else:
            # Round 2+: Construct the Sandwich

            # A. Extract Key History Elements
            my_last_arg = _get_last_message_from_role(
                state.debate.history, "ForensicAccountant"
            )
            bull_last_arg = _get_last_message_from_role(
                state.debate.history, "GrowthHunter"
            )
            judge_feedback = _get_last_message_from_role(state.debate.history, "Judge")

            # B. Self-Anchor (Consistency)
            if my_last_arg:
                messages.append(
                    AIMessage(
                        content=f"(My Previous Argument in Round 1):\n{my_last_arg}"
                    )
                )

            # C. Judge's Order (Authority)
            if judge_feedback:
                messages.append(
                    HumanMessage(
                        content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>\n"
                        f"INSTRUCTION: Address the Moderator's feedback in your response."
                    )
                )

            # D. The Target (The Enemy)
            if bull_last_arg:
                target_prompt = (
                    f"The Bull Agent has just responded.\n"
                    f"Your task is to DESTROY this specific argument:\n\n"
                    f"<opponent_argument_to_shred>\n{bull_last_arg}\n</opponent_argument_to_shred>"
                )
                messages.append(HumanMessage(content=target_prompt))

        _log_messages(messages, "BEAR_AGENT", round_num)
        response = await llm.ainvoke(messages)

        logger.info(
            f"--- Debate: Bear Agent '{ticker}' Arg (Round {round_num}):\n{response.content}..."
        )

        return {
            "debate": {
                "history": [
                    AIMessage(content=response.content, name="ForensicAccountant")
                ],
                "bear_thesis": response.content,
            },
            "current_node": "bear",
            "node_statuses": {"bear": "done", "moderator": "running"},
        }
    except Exception as e:
        logger.error(f"❌ Error in Bear Node: {str(e)}")
        fallback_msg = (
            f"Bear Analysis Error: {str(e)[:100]}. Proceeding with limited data."
        )
        return {
            "debate": {
                "history": [AIMessage(content=fallback_msg, name="ForensicAccountant")],
                "bear_thesis": fallback_msg,
            },
            "current_node": "bear",
            "node_statuses": {"bear": "error", "moderator": "running"},
        }


async def moderator_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2/3] Moderator Agent (The Judge)
    Role: Decides if consensus is reached or if debate should continue/conclude.
    Also handles the final 'Verdict' synthesis in Phase 3.
    """
    round_num = state.debate.current_round + 1
    ticker = state.fundamental.resolved_ticker or state.ticker
    logger.info(f"--- Debate: Moderator Node (Round {round_num}) ---")

    llm = get_llm()

    if round_num < 3:
        # Standard Critique/Redirect Round with Sycophancy Check
        try:
            # Check for excessive agreement (sycophancy)
            from .utils import get_sycophancy_detector

            detector = get_sycophancy_detector()
            similarity, is_sycophantic = detector.check_consensus(
                state.debate.bull_thesis or "", state.debate.bear_thesis or ""
            )

            logger.info(
                f"--- Debate: Similarity Check (Round {round_num}): {similarity:.3f} "
                f"({'SYCOPHANTIC' if is_sycophantic else 'OK'}) ---"
            )

            # Optimize context
            compressed_reports = _compress_reports(state.debate.analyst_reports)
            trimmed_history = _get_trimmed_history(state.debate.history)

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

            # 強制添加一個 Trigger，防止它開始總結
            messages.append(
                HumanMessage(
                    content="Based on the last argument, point out the logical flaw and instruct the next speaker. DO NOT SUMMARIZE. \n\nIMPORTANT: Do not make it easy for the next speaker. While asking them to refute the opponent, you must ALSO demand they provide evidence for their own weakest assumption."
                )
            )

            _log_messages(messages, "MODERATOR_CRITIQUE", round_num)
            response = await llm.ainvoke(messages)

            logger.info(
                f"--- Debate: Moderator critique (Round {round_num}):\n{response.content}..."
            )

            return {
                "debate": {
                    "history": [AIMessage(content=response.content, name="Judge")],
                    "current_round": round_num,
                },
                "current_node": "moderator",
                "node_statuses": {"moderator": "done"},
            }
        except Exception as e:
            logger.error(f"❌ Error in Moderator Node: {str(e)}")
            return {
                "debate": {
                    "history": [
                        AIMessage(
                            content=f"Moderator Error: {str(e)[:100]}", name="Judge"
                        )
                    ],
                    "current_round": round_num,
                },
                "current_node": "moderator",
                "node_statuses": {"moderator": "error"},
            }
    else:
        # Final Round: Synthesis of the DebateConclusion (Bayesian V6.0)
        logger.info("--- Debate: Final Synthesis (Verdict) ---")

        # Optimize context for final verdict
        trimmed_history = _get_trimmed_history(
            state.debate.history, max_chars=MAX_CHAR_HISTORY * 1.5
        )

        history_text = "\n\n".join(
            [f"{msg.name or 'Agent'}: {msg.content}" for msg in trimmed_history]
        )
        verdict_system = VERDICT_PROMPT.format(ticker=ticker, history=history_text)

        # Attempt structured output - fallback to manual parse if model fails
        try:
            _log_messages(
                [SystemMessage(content=verdict_system)], "MODERATOR_VERDICT", round_num
            )
            structured_llm = llm.with_structured_output(DebateConclusion)
            conclusion = await structured_llm.ainvoke(verdict_system)

            # Use mode='json' to handle Enums/Scenarios correctly
            conclusion_data = conclusion.model_dump(mode="json")

            # ==========================================
            # 🔥 Neuro-Symbolic Calculation Layer V2 🔥
            # ==========================================
            risk_profile = conclusion_data.get("risk_profile", "UNKNOWN")
            logger.info(
                f"📊 LLM Verdict: {conclusion_data.get('final_verdict')} | Profile: {risk_profile}"
            )

            # 1. 執行核心邏輯 (V2.0 Simplified)
            metrics = calculate_pragmatic_verdict(conclusion_data, ticker=ticker)

            # 2. 將計算結果更新回數據結構
            conclusion_data.update(metrics)

            logger.info(
                f"🧮 Calculated: {conclusion_data.get('final_verdict')} | "
                f"RR Ratio: {metrics.get('rr_ratio')}x | "
                f"Alpha: {metrics.get('alpha'):.2%} | "
                f"Conviction: {metrics.get('conviction')}%"
            )
            # ==========================================

        except Exception as e:
            logger.error(
                f"!!! Debate: Structured output failed: {e}. Falling back to text."
            )
            # Fallback (建議加上 risk_profile 的默認值)
            conclusion_data = {
                "scenario_analysis": {
                    "bull_case": {
                        "probability": 33,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                    "bear_case": {
                        "probability": 33,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                    "base_case": {
                        "probability": 34,
                        "outcome_description": "Error",
                        "price_implication": "FLAT",
                    },
                },
                "risk_profile": "GROWTH_TECH",  # Default fallback
                "final_verdict": "NEUTRAL",
                "winning_thesis": f"System Error: {str(e)}",
                "primary_catalyst": "N/A",
                "primary_risk": "System error",
                "supporting_factors": [],
                "rr_ratio": 0.0,
                "alpha": 0.0,
            }

        conclusion_data["debate_rounds"] = round_num

        logger.info(
            f"--- Debate: Final Verdict for {ticker} ---\n{json.dumps(conclusion_data, indent=2, default=str)}"
        )

        return {
            "debate": {
                "conclusion": conclusion_data,
                "current_round": round_num,
            },
            "current_node": "moderator",
            "node_statuses": {
                "debate": "done",
                "moderator": "done",
                "executor": "running",
            },
        }
