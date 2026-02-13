from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.agents.fundamental.data.ports import fundamental_artifact_port
from src.agents.news.data.ports import news_artifact_port
from src.agents.technical.data.ports import technical_artifact_port
from src.common.tools.logger import get_logger
from src.common.traceable import ManualProvenance, XBRLProvenance
from src.common.types import JSONObject
from src.workflow.nodes.debate.structures import EvidenceFact, FactBundle
from src.workflow.nodes.debate.tools import (
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
)

logger = get_logger(__name__)

MAX_CHAR_REPORTS = 50000
MAX_CHAR_HISTORY = 32000


@dataclass(frozen=True)
class DebateFactExtractionResult:
    ticker: str
    facts: list[EvidenceFact]
    facts_hash: str
    summary: dict[str, int]
    bundle_payload: JSONObject
    strict_facts_registry: str


class _LLMLike(Protocol):
    async def ainvoke(self, messages: object) -> object: ...


def compress_reports(
    reports: dict[str, object], max_chars: int = MAX_CHAR_REPORTS
) -> str:
    """Compress analyst reports to fit context window."""
    if not reports:
        return "{}"

    compressed = json.dumps(reports, indent=1, default=str)
    if len(compressed) <= max_chars:
        return compressed

    compressed = json.dumps(reports, separators=(",", ":"), default=str)
    if len(compressed) <= max_chars:
        return compressed

    logger.warning("⚠️ Truncating analyst reports: %d -> %d", len(compressed), max_chars)
    return compressed[:max_chars] + "\n\n[... TRUNCATED DUE TO TOKEN LIMITS ...]"


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def get_trimmed_history(
    history: list[BaseMessage], max_chars: int = MAX_CHAR_HISTORY
) -> list[BaseMessage]:
    """Get the most recent messages that fit within the character budget."""
    if not history:
        return []

    trimmed: list[BaseMessage] = []
    current_chars = 0
    for msg in reversed(history):
        msg_content = str(msg.content)
        if current_chars + len(msg_content) > max_chars:
            break
        trimmed.insert(0, msg)
        current_chars += len(msg_content)

    total_chars = sum(len(str(msg.content)) for msg in history)
    trimmed_chars = sum(len(str(msg.content)) for msg in trimmed)
    logger.info(
        "DEBATE_HISTORY_TRIM total_messages=%d total_chars=%d trimmed_messages=%d trimmed_chars=%d max_chars=%d",
        len(history),
        total_chars,
        len(trimmed),
        trimmed_chars,
        max_chars,
    )
    return trimmed


def log_messages(
    messages: list[BaseMessage], agent_name: str, round_num: int = 0
) -> None:
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
        formatted_msg += f"[{i + 1}] {role} Message:\n{content}\n" + "-" * 30 + "\n"
    formatted_msg += "=" * 50
    logger.info(formatted_msg)


def get_last_message_from_role(history: list[BaseMessage], role_name: str) -> str:
    """Extract the last message from a specific role with fallback."""
    if not history:
        return ""
    for msg in reversed(history):
        if getattr(msg, "name", None) == role_name:
            return str(msg.content)
        if (
            isinstance(msg, AIMessage)
            and msg.additional_kwargs.get("name") == role_name
        ):
            return str(msg.content)
    return ""


def artifact_ref_id_from_context(ctx: Mapping[str, object]) -> str | None:
    artifact = ctx.get("artifact")
    if not isinstance(artifact, Mapping):
        return None
    reference = artifact.get("reference")
    if not isinstance(reference, Mapping):
        return None
    artifact_id = reference.get("artifact_id")
    if not isinstance(artifact_id, str):
        return None
    return artifact_id


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    intent = state.get("intent_extraction", {})
    if not isinstance(intent, Mapping):
        return None
    ticker = intent.get("resolved_ticker")
    if not isinstance(ticker, str):
        return None
    ticker = ticker.strip()
    return ticker or None


def log_llm_config(agent_name: str, round_num: int, llm: object) -> None:
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"
    temperature = getattr(llm, "temperature", None)
    timeout = getattr(llm, "timeout", None)
    logger.info(
        "DEBATE_LLM_CONFIG agent=%s round=%d model=%s temperature=%s timeout=%s",
        agent_name,
        round_num,
        model,
        temperature,
        timeout,
    )


def log_compressed_reports(
    stage: str, ticker: str | None, compressed_reports: str, source: str
) -> None:
    logger.info(
        "DEBATE_REPORTS stage=%s ticker=%s source=%s chars=%d hash=%s",
        stage,
        ticker or "unknown",
        source,
        len(compressed_reports),
        hash_text(compressed_reports),
    )


def log_debate_context(
    agent_name: str,
    round_num: int,
    history: list[BaseMessage],
    my_last_arg: str,
    opponent_last_arg: str,
    judge_feedback: str,
) -> None:
    logger.info(
        "DEBATE_CONTEXT agent=%s round=%d history_messages=%d my_last_arg_chars=%d opponent_last_arg_chars=%d judge_feedback_chars=%d",
        agent_name,
        round_num,
        len(history),
        len(my_last_arg or ""),
        len(opponent_last_arg or ""),
        len(judge_feedback or ""),
    )


def log_llm_response(agent_name: str, round_num: int, response_text: str) -> None:
    logger.info(
        "DEBATE_OUTPUT agent=%s round=%d chars=%d hash=%s",
        agent_name,
        round_num,
        len(response_text),
        hash_text(response_text),
    )
    logger.info(
        "DEBATE_OUTPUT_TEXT agent=%s round=%d\n%s",
        agent_name,
        round_num,
        response_text,
    )


async def prepare_debate_reports(state: Mapping[str, object]) -> dict[str, object]:
    """
    Prepare compressed reports for the LLM prompt on the fly.
    This avoids mirroring large data in the state.
    """
    ticker = resolved_ticker_from_state(state)

    news_ctx = state.get("financial_news_research", {})
    news_data: dict[str, object] = {}
    news_artifact_id = (
        artifact_ref_id_from_context(news_ctx)
        if isinstance(news_ctx, Mapping)
        else None
    )
    if news_artifact_id:
        raw_data = await news_artifact_port.load_news_items_for_debate(news_artifact_id)
        if raw_data is not None:
            news_data = {"news_items": raw_data}

    ta_ctx = state.get("technical_analysis", {})
    ta_data: dict[str, object] = {}
    ta_artifact_id = (
        artifact_ref_id_from_context(ta_ctx) if isinstance(ta_ctx, Mapping) else None
    )
    if ta_artifact_id:
        payload = await technical_artifact_port.load_debate_payload(ta_artifact_id)
        if payload is not None:
            ta_data = payload

    fa_ctx = state.get("fundamental_analysis", {})
    fa_reports: list[dict[str, object]] = []
    fa_artifact_id = (
        fa_ctx.get("financial_reports_artifact_id")
        if isinstance(fa_ctx, Mapping)
        else None
    )
    if isinstance(fa_artifact_id, str):
        reports_data = await fundamental_artifact_port.load_financial_reports(
            fa_artifact_id
        )
        if reports_data is not None:
            fa_reports = reports_data

    logger.info(
        "DEBATE_REPORT_INPUT ticker=%s financials=%d news_items=%d ta_present=%s news_artifact_id=%s ta_artifact_id=%s",
        ticker or "unknown",
        len(fa_reports),
        len(news_data.get("news_items", []))
        if isinstance(news_data.get("news_items"), list)
        else 0,
        bool(ta_data),
        news_artifact_id or "none",
        ta_artifact_id or "none",
    )

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
        "ticker": ticker,
    }


async def get_debate_reports_text(
    state: Mapping[str, object], *, stage: str, ticker: str
) -> str:
    cached_reports = state.get("compressed_reports")
    if isinstance(cached_reports, str) and cached_reports:
        log_compressed_reports(stage, ticker, cached_reports, "cached")
        return cached_reports

    reports = await prepare_debate_reports(state)
    compressed_reports = compress_reports(reports)
    log_compressed_reports(stage, ticker, compressed_reports, "computed")
    return compressed_reports


async def extract_debate_facts(
    state: Mapping[str, object],
) -> DebateFactExtractionResult:
    ticker = resolved_ticker_from_state(state)
    if ticker is None:
        raise ValueError(
            "Missing intent_extraction.resolved_ticker for fact extraction"
        )

    facts: list[EvidenceFact] = []

    # Financial facts
    fa_ctx = state.get("fundamental_analysis", {})
    fa_reports: list[dict[str, object]] = []
    fa_artifact_id = (
        fa_ctx.get("financial_reports_artifact_id")
        if isinstance(fa_ctx, Mapping)
        else None
    )
    if isinstance(fa_artifact_id, str):
        reports_data = await fundamental_artifact_port.load_financial_reports(
            fa_artifact_id
        )
        if reports_data is not None:
            fa_reports = reports_data

    for report in fa_reports:
        base = report.get("base")
        if not isinstance(base, dict):
            continue
        fiscal_year_field = base.get("fiscal_year")
        fiscal_year = (
            fiscal_year_field.get("value", "N/A")
            if isinstance(fiscal_year_field, dict)
            else "N/A"
        )
        metrics = compress_financial_data([report])[0].get("metrics", {})
        if not isinstance(metrics, dict):
            continue

        for metric_name, value in metrics.items():
            fact_id = f"F{len(facts) + 1:03d}"
            prov_raw = base.get(metric_name, {})
            prov_candidate = (
                prov_raw.get("provenance") if isinstance(prov_raw, dict) else None
            )
            if not prov_candidate:
                extension = report.get("extension")
                if isinstance(extension, dict):
                    ext_field = extension.get(metric_name, {})
                    if isinstance(ext_field, dict):
                        prov_candidate = ext_field.get("provenance")

            if isinstance(prov_candidate, dict):
                provenance = XBRLProvenance(
                    concept=str(prov_candidate.get("concept") or metric_name),
                    period=str(prov_candidate.get("period") or fiscal_year),
                )
            else:
                provenance = ManualProvenance(
                    description=f"Extracted from {fiscal_year} report"
                )

            facts.append(
                EvidenceFact(
                    fact_id=fact_id,
                    source_type="financials",
                    source_weight="HIGH",
                    summary=f"[{fiscal_year}] {metric_name.replace('_', ' ').title()}: {value}",
                    value=value,
                    period=str(fiscal_year),
                    provenance=provenance,
                )
            )

    # News facts
    news_items: list[JSONObject] = []
    news_ctx = state.get("financial_news_research", {})
    news_artifact_id = (
        artifact_ref_id_from_context(news_ctx)
        if isinstance(news_ctx, Mapping)
        else None
    )
    if news_artifact_id:
        data = await news_artifact_port.load_news_items_for_debate(news_artifact_id)
        if data is not None:
            news_items = data

    for item in news_items:
        analysis = item.get("analysis", {})
        analysis_map = analysis if isinstance(analysis, dict) else {}
        key_facts = analysis_map.get("key_facts", []) or [
            {"content": analysis_map.get("summary")}
        ]

        source = item.get("source", {})
        source_name = (
            source.get("name", "Unknown") if isinstance(source, dict) else "Unknown"
        )

        published_at = item.get("published_at", "N/A")
        pub_date = str(published_at)[:10]

        for fact_item in key_facts:
            content = (
                fact_item.get("content")
                if isinstance(fact_item, dict)
                else str(fact_item)
            )
            if not content:
                continue
            fact_id = f"N{len(facts) + 1:03d}"
            facts.append(
                EvidenceFact(
                    fact_id=fact_id,
                    source_type="news",
                    source_weight="MEDIUM",
                    summary=f"({pub_date}) {source_name}: {content}",
                    provenance=ManualProvenance(
                        description=f"News: {item.get('title')}"
                    ),
                )
            )

    # Technical facts
    ta_ctx = state.get("technical_analysis", {})
    ta_artifact_id = (
        artifact_ref_id_from_context(ta_ctx) if isinstance(ta_ctx, Mapping) else None
    )
    if ta_artifact_id:
        ta_data = await technical_artifact_port.load_debate_payload(ta_artifact_id)
        if ta_data is not None:
            signal_raw = ta_data.get("signal_state")
            signal = signal_raw if isinstance(signal_raw, dict) else {}
            if signal:
                fact_id = f"T{len(facts) + 1:03d}"
                facts.append(
                    EvidenceFact(
                        fact_id=fact_id,
                        source_type="technicals",
                        source_weight="HIGH",
                        summary=f"Technical Signal: {signal.get('direction')} (Z-Score: {signal.get('z_score')})",
                        value=signal.get("z_score"),
                        provenance=ManualProvenance(
                            description=f"Technical Signal (Z-Score Analysis) from Artifact {ta_artifact_id}",
                            author="TechnicalAnalyst",
                        ),
                    )
                )

    facts_raw = [f.model_dump() for f in facts]
    facts_hash = hashlib.sha256(
        json.dumps(facts_raw, sort_keys=True, default=str).encode()
    ).hexdigest()

    bundle = FactBundle(
        ticker=ticker,
        facts=facts,
        facts_hash=facts_hash,
        generated_at=datetime.utcnow().isoformat(),
    )

    summary = {
        "financials": len([f for f in facts if f.source_type == "financials"]),
        "news": len([f for f in facts if f.source_type == "news"]),
        "technicals": len([f for f in facts if f.source_type == "technicals"]),
    }

    strict_facts_registry = "FACTS_REGISTRY (STRICT CITATION REQUIRED):\n" + "\n".join(
        [f"[{f.fact_id}] {f.summary}" for f in facts]
    )

    return DebateFactExtractionResult(
        ticker=ticker,
        facts=facts,
        facts_hash=facts_hash,
        summary=summary,
        bundle_payload=bundle.model_dump(mode="json"),
        strict_facts_registry=strict_facts_registry,
    )


async def execute_bull_round(
    *,
    state: Mapping[str, object],
    round_num: int,
    adversarial_rule: str,
    system_prompt_template: str,
    llm: _LLMLike,
) -> dict[str, object]:
    ticker = resolved_ticker_from_state(state)
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for bull agent")

    log_llm_config("BULL_AGENT", round_num, llm)
    compressed_reports = await get_debate_reports_text(
        state, stage=f"bull_r{round_num}", ticker=ticker
    )

    system_content = system_prompt_template.format(
        ticker=ticker,
        reports=compressed_reports,
        adversarial_rule=adversarial_rule,
    )
    messages: list[BaseMessage] = [SystemMessage(content=system_content)]

    if round_num > 1:
        history_raw = state.get("history", [])
        history = history_raw if isinstance(history_raw, list) else []
        my_last_arg = get_last_message_from_role(history, "GrowthHunter")
        bear_last_arg = get_last_message_from_role(history, "ForensicAccountant")
        judge_feedback = get_last_message_from_role(history, "Judge")

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

        log_debate_context(
            "BULL_AGENT",
            round_num,
            history,
            my_last_arg,
            bear_last_arg,
            judge_feedback,
        )

    log_messages(messages, "BULL_AGENT", round_num)
    response = await llm.ainvoke(messages)
    response_text = str(getattr(response, "content", ""))
    log_llm_response("BULL_AGENT", round_num, response_text)

    return {
        "history": [AIMessage(content=response_text, name="GrowthHunter")],
        "bull_thesis": response_text,
    }


async def execute_bear_round(
    *,
    state: Mapping[str, object],
    round_num: int,
    adversarial_rule: str,
    system_prompt_template: str,
    llm: _LLMLike,
) -> dict[str, object]:
    ticker = resolved_ticker_from_state(state)
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for bear agent")

    log_llm_config("BEAR_AGENT", round_num, llm)
    compressed_reports = await get_debate_reports_text(
        state, stage=f"bear_r{round_num}", ticker=ticker
    )

    system_content = system_prompt_template.format(
        ticker=ticker,
        reports=compressed_reports,
        adversarial_rule=adversarial_rule,
    )
    messages: list[BaseMessage] = [SystemMessage(content=system_content)]

    if round_num > 1:
        history_raw = state.get("history", [])
        history = history_raw if isinstance(history_raw, list) else []
        my_last_arg = get_last_message_from_role(history, "ForensicAccountant")
        bull_last_arg = get_last_message_from_role(history, "GrowthHunter")
        judge_feedback = get_last_message_from_role(history, "Judge")

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

        log_debate_context(
            "BEAR_AGENT",
            round_num,
            history,
            my_last_arg,
            bull_last_arg,
            judge_feedback,
        )

    log_messages(messages, "BEAR_AGENT", round_num)
    response = await llm.ainvoke(messages)
    response_text = str(getattr(response, "content", ""))
    log_llm_response("BEAR_AGENT", round_num, response_text)

    return {
        "history": [AIMessage(content=response_text, name="ForensicAccountant")],
        "bear_thesis": response_text,
    }


async def execute_moderator_round(
    *,
    state: Mapping[str, object],
    round_num: int,
    system_prompt_template: str,
    llm: _LLMLike,
    detector: object,
) -> dict[str, object]:
    ticker = resolved_ticker_from_state(state)
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for moderator")

    log_llm_config("MODERATOR", round_num, llm)

    debate_ctx = state.get("debate", {})
    debate_map = debate_ctx if isinstance(debate_ctx, Mapping) else {}
    bull_thesis = str(debate_map.get("bull_thesis") or "")
    bear_thesis = str(debate_map.get("bear_thesis") or "")
    similarity, is_sycophantic = detector.check_consensus(bull_thesis, bear_thesis)
    logger.info(
        "DEBATE_SYCOPHANCY_CHECK round=%d similarity=%.4f threshold=0.8 flagged=%s",
        round_num,
        similarity,
        is_sycophantic,
    )

    compressed_reports = await get_debate_reports_text(
        state, stage=f"moderator_r{round_num}", ticker=ticker
    )
    history_raw = state.get("history", [])
    history = history_raw if isinstance(history_raw, list) else []
    trimmed_history = get_trimmed_history(history)

    system_content = system_prompt_template.format(
        ticker=ticker, reports=compressed_reports
    )
    if is_sycophantic:
        system_content += "\n⚠️ SYCOPHANCY DETECTED. Demand counter-arguments."

    messages: list[BaseMessage] = [
        SystemMessage(content=system_content)
    ] + trimmed_history
    messages.append(HumanMessage(content="Point out logical flaws. DO NOT SUMMARIZE."))

    log_messages(messages, "MODERATOR_CRITIQUE", round_num)
    response = await llm.ainvoke(messages)
    response_text = str(getattr(response, "content", ""))
    log_llm_response("MODERATOR_CRITIQUE", round_num, response_text)

    return {
        "history": [AIMessage(content=response_text, name="Judge")],
        "current_round": round_num,
    }
