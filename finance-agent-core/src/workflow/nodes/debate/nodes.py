import json
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.interface.schemas import AgentOutputArtifact
from src.utils.logger import get_logger

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
from .subgraph_state import DebateState
from .utils import (
    calculate_pragmatic_verdict,
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
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


async def debate_aggregator_node(state: DebateState) -> dict[str, Any]:
    # Compress data before passing to debate state
    # Now that we've removed the legacy .output fields, we read from the standardized .artifact.data

    # News Data
    news_artifact = state.financial_news_research.artifact
    news_data = {}
    if news_artifact:
        if hasattr(news_artifact, "data"):
            news_data = news_artifact.data
        elif isinstance(news_artifact, dict):
            news_data = news_artifact.get("data", {})

    # Technical Analysis Data
    ta_artifact = state.technical_analysis.artifact
    ta_data = {}
    if ta_artifact:
        if hasattr(ta_artifact, "data"):
            ta_data = ta_artifact.data
        elif isinstance(ta_artifact, dict):
            ta_data = ta_artifact.get("data", {})

    # === Compress Data ===
    clean_financials = compress_financial_data(
        state.fundamental_analysis.financial_reports
    )
    clean_news = compress_news_data(news_data)
    clean_ta = compress_ta_data(ta_data)

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
        "technical_analysis": {
            "data": clean_ta,
            "source_weight": "MEDIUM",
            "rationale": "Quantitative source: Fractional differentiation analysis (statistical signals)",
        },
        "ticker": state.intent_extraction.resolved_ticker or state.ticker,
    }

    # In the linear DAG, aggregator always leads to Round 1 (Parallel)
    next_progress = {
        "debate_aggregator": "done",
        "r1_bull": "running",
        "r1_bear": "running",
    }

    return {
        "debate": {"analyst_reports": reports},
        "current_node": "debate_aggregator",
        "internal_progress": next_progress,
    }


# --- Agent Logic Helpers (DRY) ---


async def _execute_bull_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, Any]:
    """Internal helper for Bull logic across rounds."""
    ticker = state.intent_extraction.resolved_ticker or state.ticker
    try:
        llm = get_llm()
        compressed_reports = _compress_reports(state.debate.analyst_reports)

        system_content = BULL_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )
        messages = [SystemMessage(content=system_content)]

        # Context Sandwich for R2+
        if round_num > 1:
            my_last_arg = _get_last_message_from_role(
                state.debate.history, "GrowthHunter"
            )
            bear_last_arg = _get_last_message_from_role(
                state.debate.history, "ForensicAccountant"
            )
            judge_feedback = _get_last_message_from_role(state.debate.history, "Judge")

            if my_last_arg:
                messages.append(
                    AIMessage(content=f"(My Previous Argument):\n{my_last_arg}")
                )
            if judge_feedback:
                messages.append(
                    HumanMessage(
                        content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>"
                    )
                )
            if bear_last_arg:
                messages.append(
                    HumanMessage(content=f"DESTROY this argument:\n\n{bear_last_arg}")
                )

        _log_messages(messages, "BULL_AGENT", round_num)
        response = await llm.ainvoke(messages)

        return {
            "history": [AIMessage(content=response.content, name="GrowthHunter")],
            "thesis": response.content,
        }
    except Exception as e:
        logger.error(f"❌ Error in Bull Logic (R{round_num}): {str(e)}")
        raise e


async def _execute_bear_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, Any]:
    """Internal helper for Bear logic across rounds."""
    ticker = state.intent_extraction.resolved_ticker or state.ticker
    try:
        llm = get_llm()
        compressed_reports = _compress_reports(state.debate.analyst_reports)

        system_content = BEAR_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )
        messages = [SystemMessage(content=system_content)]

        # Context Sandwich for R2+
        if round_num > 1:
            my_last_arg = _get_last_message_from_role(
                state.debate.history, "ForensicAccountant"
            )
            bull_last_arg = _get_last_message_from_role(
                state.debate.history, "GrowthHunter"
            )
            judge_feedback = _get_last_message_from_role(state.debate.history, "Judge")

            if my_last_arg:
                messages.append(
                    AIMessage(content=f"(My Previous Argument):\n{my_last_arg}")
                )
            if judge_feedback:
                messages.append(
                    HumanMessage(
                        content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>"
                    )
                )
            if bull_last_arg:
                messages.append(
                    HumanMessage(content=f"DESTROY this argument:\n\n{bull_last_arg}")
                )

        _log_messages(messages, "BEAR_AGENT", round_num)
        response = await llm.ainvoke(messages)

        return {
            "history": [AIMessage(content=response.content, name="ForensicAccountant")],
            "thesis": response.content,
        }
    except Exception as e:
        logger.error(f"❌ Error in Bear Logic (R{round_num}): {str(e)}")
        raise e


async def _execute_moderator_critique(
    state: DebateState, round_num: int
) -> dict[str, Any]:
    """Internal helper for Moderator Critique across rounds."""
    ticker = state.intent_extraction.resolved_ticker or state.ticker
    try:
        llm = get_llm()
        from .utils import get_sycophancy_detector

        detector = get_sycophancy_detector()
        similarity, is_sycophantic = detector.check_consensus(
            state.debate.bull_thesis or "", state.debate.bear_thesis or ""
        )

        compressed_reports = _compress_reports(state.debate.analyst_reports)
        trimmed_history = _get_trimmed_history(state.debate.history)
        system_content = MODERATOR_SYSTEM_PROMPT.format(
            ticker=ticker, reports=compressed_reports
        )

        if is_sycophantic:
            system_content += "\n⚠️ SYCOPHANCY DETECTED. Demand counter-arguments."

        messages = [SystemMessage(content=system_content)] + trimmed_history
        messages.append(
            HumanMessage(content="Point out logical flaws. DO NOT SUMMARIZE.")
        )

        _log_messages(messages, "MODERATOR_CRITIQUE", round_num)
        response = await llm.ainvoke(messages)

        return {
            "history": [AIMessage(content=response.content, name="Judge")],
            "current_round": round_num,
        }
    except Exception as e:
        logger.error(f"❌ Error in Moderator Critique (R{round_num}): {str(e)}")
        raise e


# --- EXPLICIT NODES ---


# --- Round 1 ---
async def r1_bull_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bull_agent(state, 1, BULL_R1_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bull_thesis": res["thesis"]},
        "internal_progress": {
            "r1_bull": "done",
            "r1_bear": "running",
        },  # Helpful if parallel UI updates
    }


async def r1_bear_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bear_agent(state, 1, BEAR_R1_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bear_thesis": res["thesis"]},
        "internal_progress": {"r1_bear": "done"},
    }


async def r1_moderator_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_moderator_critique(state, 1)
    return {
        "debate": res,
        "internal_progress": {"r1_moderator": "done", "r2_bull": "running"},
    }


# --- Round 2 ---
async def r2_bull_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bull_agent(state, 2, BULL_R2_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bull_thesis": res["thesis"]},
        "internal_progress": {"r2_bull": "done", "r2_bear": "running"},
    }


async def r2_bear_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bear_agent(state, 2, BEAR_R2_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bear_thesis": res["thesis"]},
        "internal_progress": {"r2_bear": "done", "r2_moderator": "running"},
    }


async def r2_moderator_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_moderator_critique(state, 2)
    return {
        "debate": res,
        "internal_progress": {"r2_moderator": "done", "r3_bear": "running"},
    }


# --- Round 3 ---
async def r3_bear_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bear_agent(state, 3, BEAR_R2_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bear_thesis": res["thesis"]},
        "internal_progress": {"r3_bear": "done", "r3_bull": "running"},
    }


async def r3_bull_node(state: DebateState) -> dict[str, Any]:
    res = await _execute_bull_agent(state, 3, BULL_R2_ADVERSARIAL)
    return {
        "debate": {"history": res["history"], "bull_thesis": res["thesis"]},
        "internal_progress": {"r3_bull": "done", "verdict": "running"},
    }


# --- Final Verdict ---
async def verdict_node(state: DebateState) -> dict[str, Any]:
    """Final Verdict Node"""
    ticker = state.intent_extraction.resolved_ticker or state.ticker
    try:
        llm = get_llm()
        trimmed_history = _get_trimmed_history(
            state.debate.history, max_chars=MAX_CHAR_HISTORY * 1.5
        )
        history_text = "\n\n".join(
            [f"{msg.name or 'Agent'}: {msg.content}" for msg in trimmed_history]
        )
        verdict_system = VERDICT_PROMPT.format(ticker=ticker, history=history_text)

        _log_messages([SystemMessage(content=verdict_system)], "VERDICT", 3)
        structured_llm = llm.with_structured_output(DebateConclusion)
        conclusion = await structured_llm.ainvoke(verdict_system)
        conclusion_data = conclusion.model_dump(mode="json")

        metrics = calculate_pragmatic_verdict(conclusion_data, ticker=ticker)
        conclusion_data.update(metrics)
        conclusion_data["debate_rounds"] = 3

        return {
            "artifact": AgentOutputArtifact(
                summary=f"Verdict: {conclusion_data.get('decision', 'PENDING')} (Confidence: {conclusion_data.get('confidence_score', 0)}%)",
                data=conclusion_data,
            ),
            "internal_progress": {"verdict": "done"},
            # [BSP Fix] Emit status immediately to bypass LangGraph's sync barrier
            "node_statuses": {"debate": "done"},
        }
    except Exception as e:
        logger.error(f"❌ Error in Verdict Node: {str(e)}")
        return {"internal_progress": {"verdict": "error"}}
