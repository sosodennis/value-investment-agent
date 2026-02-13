import json

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from src.agents.debate.application.use_cases import (
    MAX_CHAR_HISTORY,
    execute_bear_round,
    execute_bull_round,
    execute_moderator_round,
    extract_debate_facts,
)
from src.agents.debate.application.use_cases import (
    compress_reports as _compress_reports,
)
from src.agents.debate.application.use_cases import (
    get_trimmed_history as _get_trimmed_history,
)
from src.agents.debate.application.use_cases import (
    log_compressed_reports as _log_compressed_reports,
)
from src.agents.debate.application.use_cases import (
    log_llm_config as _log_llm_config,
)
from src.agents.debate.application.use_cases import (
    log_llm_response as _log_llm_response,
)
from src.agents.debate.application.use_cases import (
    log_messages as _log_messages,
)
from src.agents.debate.application.use_cases import (
    prepare_debate_reports as _prepare_debate_reports,
)
from src.agents.debate.application.use_cases import (
    resolved_ticker_from_state as _resolved_ticker_from_state,
)
from src.agents.debate.data.market_data import (
    get_current_risk_free_rate,
    get_dynamic_payoff_map,
)
from src.agents.debate.data.ports import debate_artifact_port
from src.agents.debate.domain.models import DebateConclusion, EvidenceFact
from src.agents.debate.domain.services import (
    calculate_pragmatic_verdict,
    get_sycophancy_detector,
)
from src.agents.debate.domain.validators import FactValidator
from src.agents.debate.interface.mappers import summarize_debate_for_preview
from src.common.contracts import (
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    OUTPUT_KIND_DEBATE,
)
from src.common.tools.llm import get_llm
from src.common.tools.logger import get_logger
from src.interface.canonical_serializers import canonicalize_debate_artifact_data
from src.interface.schemas import ArtifactReference, build_artifact_payload

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
from .subgraph_state import DebateState

logger = get_logger(__name__)

# --- LLM Shared Config ---
DEFAULT_MODEL = "arcee-ai/trinity-large-preview:free"


async def debate_aggregator_node(state: DebateState) -> Command:
    """
    Initializes debate progress and pre-computes compressed reports.
    Data compression is cached in the state to prevent redundant processing.
    """
    ticker = _resolved_ticker_from_state(state)
    if ticker is None:
        return Command(
            update={
                "internal_progress": {"debate_aggregator": "error"},
                "node_statuses": {"debate": "error"},
                "error_logs": [
                    {
                        "node": "debate_aggregator",
                        "error": "Missing intent_extraction.resolved_ticker",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    # Pre-compute and cache reports
    reports = await _prepare_debate_reports(state)
    compressed_reports = _compress_reports(reports)
    _log_compressed_reports("debate_aggregator", ticker, compressed_reports, "computed")

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
        goto=["fact_extractor"],
    )


async def fact_extractor_node(state: DebateState) -> Command:
    """
    Extracts deterministic facts from financials, news, and technicals.
    Grounds the debate by providing stable IDs for evidence citation.
    """
    ticker = _resolved_ticker_from_state(state)
    if ticker is None:
        return Command(
            update={
                "fact_extraction_status": "error",
                "internal_progress": {"fact_extractor": "error"},
                "node_statuses": {"debate": "error"},
                "error_logs": [
                    {
                        "node": "fact_extractor",
                        "error": "Missing intent_extraction.resolved_ticker",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )
    logger.info("FACT_EXTRACTION_START ticker=%s", ticker)
    extracted = await extract_debate_facts(state)
    artifact_id = await debate_artifact_port.save_facts_bundle(
        data=extracted.bundle_payload,
        produced_by="debate.fact_extractor",
        key_prefix=extracted.ticker,
    )
    logger.info("FACT_EXTRACTION_DONE ticker=%s facts=%d", ticker, len(extracted.facts))

    return Command(
        update={
            "facts_artifact_id": artifact_id,
            "facts_hash": extracted.facts_hash,
            "facts_summary": extracted.summary,
            "fact_extraction_status": "done",
            "compressed_reports": extracted.strict_facts_registry,
        },
        goto=["r1_bull", "r1_bear"],
    )


# --- Agent Logic Helpers (DRY) ---


async def _execute_bull_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, object]:
    """Internal helper for Bull logic across rounds."""
    llm = get_llm()
    return await execute_bull_round(
        state=state,
        round_num=round_num,
        adversarial_rule=adversarial_rule,
        system_prompt_template=BULL_AGENT_SYSTEM_PROMPT,
        llm=llm,
    )


async def _execute_bear_agent(
    state: DebateState, round_num: int, adversarial_rule: str
) -> dict[str, object]:
    """Internal helper for Bear logic across rounds."""
    llm = get_llm()
    return await execute_bear_round(
        state=state,
        round_num=round_num,
        adversarial_rule=adversarial_rule,
        system_prompt_template=BEAR_AGENT_SYSTEM_PROMPT,
        llm=llm,
    )


async def _execute_moderator_critique(
    state: DebateState, round_num: int
) -> dict[str, object]:
    """Internal helper for Moderator Critique across rounds."""
    llm = get_llm()

    return await execute_moderator_round(
        state=state,
        round_num=round_num,
        system_prompt_template=MODERATOR_SYSTEM_PROMPT,
        llm=llm,
        detector=get_sycophancy_detector(),
    )


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
            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_DEBATE,
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
            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_DEBATE,
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
    ticker = _resolved_ticker_from_state(state)
    if ticker is None:
        return Command(
            update={
                "internal_progress": {"verdict": "error"},
                "node_statuses": {"debate": "error"},
                "error_logs": [
                    {
                        "node": "verdict",
                        "error": "Missing intent_extraction.resolved_ticker",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )
    try:
        llm = get_llm()
        _log_llm_config("VERDICT", 3, llm)
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
        _log_llm_response(
            "VERDICT_JSON",
            3,
            json.dumps(conclusion_data, ensure_ascii=True, indent=2),
        )

        metrics = calculate_pragmatic_verdict(
            conclusion_data,
            ticker=ticker,
            get_risk_free_rate=get_current_risk_free_rate,
            get_payoff_map=get_dynamic_payoff_map,
        )
        conclusion_data.update(metrics)
        conclusion_data["debate_rounds"] = 3

        # Citation Audit
        bull_history = [m.content for m in history if m.name == "GrowthHunter"]
        bear_history = [m.content for m in history if m.name == "ForensicAccountant"]

        # [P1 Fix] Fetch facts from artifact (Single Source of Truth)
        valid_facts = []
        facts_artifact_id = state.get("facts_artifact_id")
        if isinstance(facts_artifact_id, str):
            facts_bundle = await debate_artifact_port.load_facts_bundle(
                facts_artifact_id
            )
            if facts_bundle is not None:
                valid_facts = [
                    EvidenceFact(**fact.model_dump()) for fact in facts_bundle.facts
                ]

        audit_results = {
            "bull": FactValidator.validate_citations(
                "\n".join(bull_history), valid_facts
            ),
            "bear": FactValidator.validate_citations(
                "\n".join(bear_history), valid_facts
            ),
        }
        conclusion_data["citation_audit"] = audit_results

        # Prepare full report data (Conclusion + History + Facts)
        full_report_data_raw = {
            **conclusion_data,
            "facts": [f.model_dump(mode="json") for f in valid_facts],
            "history": [msg.model_dump(mode="json") for msg in history],
        }
        full_report_data = canonicalize_debate_artifact_data(full_report_data_raw)

        # Save artifact (L3) - Now full report, not just transcript
        report_id = await debate_artifact_port.save_final_report(
            data=full_report_data,
            produced_by="debate.verdict",
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
                    type=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
                )

            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_DEBATE,
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
