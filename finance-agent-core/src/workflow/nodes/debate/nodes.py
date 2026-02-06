import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from src.common.tools.llm import get_llm
from src.common.tools.logger import get_logger
from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.services.artifact_manager import artifact_manager

from .mappers import summarize_debate_for_preview
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
from .tools import (
    calculate_pragmatic_verdict,
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
)

logger = get_logger(__name__)

# --- LLM Shared Config ---
DEFAULT_MODEL = "arcee-ai/trinity-large-preview:free"
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


def _log_messages(messages: list, agent_name: str, round_num: int = 0):
    """Log full message content for audit/debugging."""
    log_header = f"PROMPT SENT TO {agent_name}"
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


async def _prepare_debate_reports(state: DebateState) -> dict:
    """
    Prepare compressed reports for the LLM prompt on the fly.
    This avoids mirroring large data in the state (Engineering Charter §3.4).
    """
    # News Data
    news_ctx = state.get("financial_news_research", {})
    news_artifact = news_ctx.get("artifact")
    news_data = {}

    # Try getting from artifact reference (L3)
    artifact_id = None
    if news_artifact:
        # Check if it's an object or dict
        if hasattr(news_artifact, "reference") and news_artifact.reference:
            artifact_id = news_artifact.reference.artifact_id
        elif isinstance(news_artifact, dict) and news_artifact.get("reference"):
            ref = news_artifact.get("reference")
            if isinstance(ref, dict):
                artifact_id = ref.get("artifact_id")
            elif hasattr(ref, "artifact_id"):
                artifact_id = ref.artifact_id

    # Fallback to news_items_artifact_id
    if not artifact_id:
        artifact_id = news_ctx.get("news_items_artifact_id")

    if artifact_id:
        artifact_obj = await artifact_manager.get_artifact(artifact_id)
        if artifact_obj and hasattr(artifact_obj, "data"):
            raw_data = artifact_obj.data
            # News data compression expects a dict with "news_items" key
            if isinstance(raw_data, list):
                news_data = {"news_items": raw_data}
            elif isinstance(raw_data, dict):
                news_data = raw_data

    # Technical Analysis Data
    ta_ctx = state.get("technical_analysis", {})
    ta_artifact = ta_ctx.get("artifact")
    ta_data = {}

    artifact_id = None
    if ta_artifact:
        if hasattr(ta_artifact, "reference") and ta_artifact.reference:
            artifact_id = ta_artifact.reference.artifact_id
        elif isinstance(ta_artifact, dict) and ta_artifact.get("reference"):
            ref = ta_artifact.get("reference")
            if isinstance(ref, dict):
                artifact_id = ref.get("artifact_id")
            elif hasattr(ref, "artifact_id"):
                artifact_id = ref.artifact_id

    # Fallback to chart_data_id or price_artifact_id
    if not artifact_id:
        artifact_id = ta_ctx.get("chart_data_id") or ta_ctx.get("price_artifact_id")

    if artifact_id:
        artifact_obj = await artifact_manager.get_artifact(artifact_id)
        if artifact_obj and hasattr(artifact_obj, "data"):
            ta_data = artifact_obj.data

    # Fundamental Analysis Data
    fa_reports = state.get("fundamental_analysis", {}).get("financial_reports", [])

    return {
        "financials": {
            "data": compress_financial_data(fa_reports),
            "source_weight": "HIGH",
            "rationale": "Primary source: SEC XBRL filings (audited, regulatory-grade data)",
        },
        "news": {
            "data": compress_news_data(news_data),
            "source_weight": "MEDIUM",
            "rationale": "Secondary source: Curated financial news (editorial bias possible)",
        },
        "technical_analysis": {
            "data": compress_ta_data(ta_data),
            "source_weight": "HIGH",
            "rationale": "Quantitative source: Fractional differentiation analysis (statistical signals)",
        },
        "ticker": state.get("intent_extraction", {}).get("resolved_ticker")
        or state.get("ticker"),
    }


async def debate_aggregator_node(state: DebateState) -> Command:
    """
    Initializes debate progress and pre-computes compressed reports.
    Data compression is cached in the state to prevent redundant processing.
    """
    # Pre-compute and cache reports
    reports = await _prepare_debate_reports(state)
    compressed_reports = _compress_reports(reports)

    next_progress = {
        "debate_aggregator": "done",
        "r1_bull": "running",
        "r1_bear": "running",
    }

    return Command(
        update={
            "current_node": "debate_aggregator",
            "internal_progress": next_progress,
            "node_statuses": {"debate": "running"},
            "compressed_reports": compressed_reports,
        },
        goto=["r1_bull", "r1_bear"],
    )


# --- Agent Logic Helpers (DRY) ---


async def _execute_bull_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, Any]:
    """Internal helper for Bull logic across rounds."""
    ticker = state.get("intent_extraction", {}).get("resolved_ticker") or state.get(
        "ticker"
    )
    try:
        llm = get_llm()

        # Use cached reports if available, fallback to on-the-fly computation
        compressed_reports = state.get("compressed_reports")
        if not compressed_reports:
            reports = await _prepare_debate_reports(state)
            compressed_reports = _compress_reports(reports)

        system_content = BULL_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )
        messages = [SystemMessage(content=system_content)]

        # Context Sandwich for R2+
        if round_num > 1:
            history = state.get("history", [])
            my_last_arg = _get_last_message_from_role(history, "GrowthHunter")
            bear_last_arg = _get_last_message_from_role(history, "ForensicAccountant")
            judge_feedback = _get_last_message_from_role(history, "Judge")

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
            "bull_thesis": response.content,
        }
    except Exception as e:
        logger.error(f"❌ Error in Bull Logic (R{round_num}): {str(e)}")
        raise e


async def _execute_bear_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, Any]:
    """Internal helper for Bear logic across rounds."""
    ticker = state.get("intent_extraction", {}).get("resolved_ticker") or state.get(
        "ticker"
    )
    try:
        llm = get_llm()

        # Use cached reports if available, fallback to on-the-fly computation
        compressed_reports = state.get("compressed_reports")
        if not compressed_reports:
            reports = await _prepare_debate_reports(state)
            compressed_reports = _compress_reports(reports)

        system_content = BEAR_AGENT_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=compressed_reports,
            adversarial_rule=adversarial_rule,
        )
        messages = [SystemMessage(content=system_content)]

        # Context Sandwich for R2+
        if round_num > 1:
            history = state.get("history", [])
            my_last_arg = _get_last_message_from_role(history, "ForensicAccountant")
            bull_last_arg = _get_last_message_from_role(history, "GrowthHunter")
            judge_feedback = _get_last_message_from_role(history, "Judge")

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
            "bear_thesis": response.content,
        }
    except Exception as e:
        logger.error(f"❌ Error in Bear Logic (R{round_num}): {str(e)}")
        raise e


async def _execute_moderator_critique(
    state: DebateState, round_num: int
) -> dict[str, Any]:
    """Internal helper for Moderator Critique across rounds."""
    ticker = state.get("intent_extraction", {}).get("resolved_ticker") or state.get(
        "ticker"
    )
    try:
        llm = get_llm()
        from .tools import get_sycophancy_detector

        detector = get_sycophancy_detector()
        similarity, is_sycophantic = detector.check_consensus(
            state.get("debate", {}).get("bull_thesis") or "",
            state.get("debate", {}).get("bear_thesis") or "",
        )

        reports = await _prepare_debate_reports(state)
        compressed_reports = _compress_reports(reports)
        trimmed_history = _get_trimmed_history(state.get("history", []))

        # Use cached reports if available, fallback to on-the-fly computation
        cached_reports = state.get("compressed_reports")
        if cached_reports:
            compressed_reports = cached_reports

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
async def r1_bull_node(state: DebateState) -> Command:
    try:
        res = await _execute_bull_agent(state, 1, BULL_R1_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bull_thesis": res["bull_thesis"],
                "internal_progress": {
                    "r1_bull": "done",
                    "r1_bear": "running",
                },
            },
            goto="r1_moderator",
        )
    except Exception as e:
        logger.error(f"r1_bull failed: {e}")
        error_msg = f"Bull Agent failed in Round 1: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(content=f"[SYSTEM] {error_msg}", name="GrowthHunter")
                ],
                "bull_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r1_bull": "error", "r1_bear": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r1_bull", "error": str(e), "severity": "error"}
                ],
            },
            goto="r1_moderator",
        )


async def r1_bear_node(state: DebateState) -> Command:
    try:
        res = await _execute_bear_agent(state, 1, BEAR_R1_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bear_thesis": res["bear_thesis"],
                "internal_progress": {"r1_bear": "done"},
            },
            goto="r1_moderator",
        )
    except Exception as e:
        logger.error(f"r1_bear failed: {e}")
        error_msg = f"Bear Agent failed in Round 1: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(
                        content=f"[SYSTEM] {error_msg}", name="ForensicAccountant"
                    )
                ],
                "bear_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r1_bear": "error"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r1_bear", "error": str(e), "severity": "error"}
                ],
            },
            goto="r1_moderator",
        )


async def r1_moderator_node(state: DebateState) -> Command:
    try:
        res = await _execute_moderator_critique(state, 1)
        # [NEW] Emit progress artifact
        try:
            preview = summarize_debate_for_preview(
                {
                    "current_round": 1,
                    "winning_thesis": "Round 1 complete, synthesizing arguments...",
                }
            )
            artifact = AgentOutputArtifact(
                summary="Cognitive Debate: Round 1 moderator critique complete",
                preview=preview,
                reference=None,
            )
        except Exception:
            artifact = None

        return Command(
            update={
                "history": res["history"],
                "debate": {"current_round": res["current_round"], "artifact": artifact},
                "internal_progress": {"r1_moderator": "done", "r2_bull": "running"},
            },
            goto="r2_bull",
        )
    except Exception as e:
        logger.error(f"r1_moderator failed: {e}")
        error_msg = f"Moderator failed in Round 1: {str(e)}"
        # Inject dummy moderator msg so history is not broken
        return Command(
            update={
                "history": [AIMessage(content=f"[SYSTEM] {error_msg}", name="Judge")],
                "debate": {"current_round": 1},
                "internal_progress": {"r1_moderator": "error", "r2_bull": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r1_moderator", "error": str(e), "severity": "error"}
                ],
            },
            goto="r2_bull",
        )


# --- Round 2 ---
async def r2_bull_node(state: DebateState) -> Command:
    try:
        res = await _execute_bull_agent(state, 2, BULL_R2_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bull_thesis": res["bull_thesis"],
                "internal_progress": {"r2_bull": "done", "r2_bear": "running"},
            },
            goto="r2_bear",
        )
    except Exception as e:
        logger.error(f"r2_bull failed: {e}")
        error_msg = f"Bull Agent failed in Round 2: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(content=f"[SYSTEM] {error_msg}", name="GrowthHunter")
                ],
                "bull_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r2_bull": "error", "r2_bear": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r2_bull", "error": str(e), "severity": "error"}
                ],
            },
            goto="r2_bear",
        )


async def r2_bear_node(state: DebateState) -> Command:
    try:
        res = await _execute_bear_agent(state, 2, BEAR_R2_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bear_thesis": res["bear_thesis"],
                "internal_progress": {"r2_bear": "done", "r2_moderator": "running"},
            },
            goto="r2_moderator",
        )
    except Exception as e:
        logger.error(f"r2_bear failed: {e}")
        error_msg = f"Bear Agent failed in Round 2: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(
                        content=f"[SYSTEM] {error_msg}", name="ForensicAccountant"
                    )
                ],
                "bear_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r2_bear": "error", "r2_moderator": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r2_bear", "error": str(e), "severity": "error"}
                ],
            },
            goto="r2_moderator",
        )


async def r2_moderator_node(state: DebateState) -> Command:
    try:
        res = await _execute_moderator_critique(state, 2)
        # [NEW] Emit progress artifact
        try:
            preview = summarize_debate_for_preview(
                {
                    "current_round": 2,
                    "winning_thesis": "Round 2 cross-review complete, assessing vulnerabilities...",
                }
            )
            artifact = AgentOutputArtifact(
                summary="Cognitive Debate: Round 2 adversarial analysis complete",
                preview=preview,
                reference=None,
            )
        except Exception:
            artifact = None

        return Command(
            update={
                "history": res["history"],
                "debate": {"current_round": res["current_round"], "artifact": artifact},
                "internal_progress": {"r2_moderator": "done", "r3_bear": "running"},
            },
            goto="r3_bear",
        )
    except Exception as e:
        logger.error(f"r2_moderator failed: {e}")
        error_msg = f"Moderator failed in Round 2: {str(e)}"
        return Command(
            update={
                "history": [AIMessage(content=f"[SYSTEM] {error_msg}", name="Judge")],
                "debate": {"current_round": 2},
                "internal_progress": {"r2_moderator": "error", "r3_bear": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r2_moderator", "error": str(e), "severity": "error"}
                ],
            },
            goto="r3_bear",
        )


# --- Round 3 ---
async def r3_bear_node(state: DebateState) -> Command:
    try:
        res = await _execute_bear_agent(state, 3, BEAR_R2_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bear_thesis": res["bear_thesis"],
                "internal_progress": {"r3_bear": "done", "r3_bull": "running"},
            },
            goto="r3_bull",
        )
    except Exception as e:
        logger.error(f"r3_bear failed: {e}")
        error_msg = f"Bear Agent failed in Round 3: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(
                        content=f"[SYSTEM] {error_msg}", name="ForensicAccountant"
                    )
                ],
                "bear_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r3_bear": "error", "r3_bull": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r3_bear", "error": str(e), "severity": "error"}
                ],
            },
            goto="r3_bull",
        )


async def r3_bull_node(state: DebateState) -> Command:
    try:
        res = await _execute_bull_agent(state, 3, BULL_R2_ADVERSARIAL)
        return Command(
            update={
                "history": res["history"],
                "bull_thesis": res["bull_thesis"],
                "internal_progress": {"r3_bull": "done", "verdict": "running"},
            },
            goto="verdict",
        )
    except Exception as e:
        logger.error(f"r3_bull failed: {e}")
        error_msg = f"Bull Agent failed in Round 3: {str(e)}"
        return Command(
            update={
                "history": [
                    AIMessage(content=f"[SYSTEM] {error_msg}", name="GrowthHunter")
                ],
                "bull_thesis": "[ARGUMENT MISSING]",
                "internal_progress": {"r3_bull": "error", "verdict": "running"},
                "node_statuses": {"debate": "degraded"},
                "error_logs": [
                    {"node": "r3_bull", "error": str(e), "severity": "error"}
                ],
            },
            goto="verdict",
        )


# --- Final Verdict ---
async def verdict_node(state: DebateState) -> Command:
    """Final Verdict Node"""
    ticker = state.get("intent_extraction", {}).get("resolved_ticker") or state.get(
        "ticker"
    )
    try:
        llm = get_llm()
        history = state.get("history", [])
        trimmed_history = _get_trimmed_history(
            history, max_chars=MAX_CHAR_HISTORY * 1.5
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

        # Prepare full report data (Conclusion + History)
        full_report_data = {
            **conclusion_data,
            "kind": "success",  # Align with DebateSuccess frontend type
            "history": [msg.dict() if hasattr(msg, "dict") else msg for msg in history],
        }

        # Save artifact (L3) - Now full report, not just transcript
        report_id = await artifact_manager.save_artifact(
            data=full_report_data,
            artifact_type="debate_final_report",
            key_prefix=ticker,
        )

        # [NEW] Generate final artifact
        try:
            preview = summarize_debate_for_preview(conclusion_data)
            reference = None
            if report_id:
                reference = ArtifactReference(
                    artifact_id=report_id,
                    download_url=f"/api/artifacts/{report_id}",
                    type="debate_final_report",
                )

            artifact = AgentOutputArtifact(
                summary=f"Debate: {preview.get('verdict_display')}",
                preview=preview,
                reference=reference,
            )
        except Exception as e:
            logger.error(f"Failed to generate debate artifact: {e}")
            artifact = None

        debate_update = {
            "status": "success",
            "final_verdict": conclusion_data.get("decision")
            or conclusion_data.get("final_verdict"),
            "kelly_confidence": conclusion_data.get("kelly_confidence"),
            "winning_thesis": conclusion_data.get("winning_thesis"),
            "primary_catalyst": conclusion_data.get("primary_catalyst"),
            "primary_risk": conclusion_data.get("primary_risk"),
            "report_id": report_id,
            "current_round": 3,
        }
        if artifact:
            debate_update["artifact"] = artifact

        return Command(
            update={
                "debate": debate_update,
                "internal_progress": {"verdict": "done"},
                "node_statuses": {"debate": "done"},
            },
            goto=END,
        )
    except Exception as e:
        logger.error(f"❌ Error in Verdict Node: {str(e)}")
        # In case of error, we must still return a Command
        return Command(
            update={
                "internal_progress": {"verdict": "error"},
                "node_statuses": {"debate": "error"},
                "error_logs": [
                    {
                        "node": "verdict",
                        "error": f"Verdict generation failed: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )
