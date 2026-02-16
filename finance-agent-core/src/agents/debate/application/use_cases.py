from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from langchain_core.messages import AIMessage

from src.agents.debate.application.debate_context import (
    build_debate_artifact_context,
    build_debate_conversation_context,
)
from src.agents.debate.application.dto import DebateFactExtractionResult
from src.agents.debate.application.ports import (
    DebateSourceReaderPort,
    SycophancyDetectorPort,
)
from src.agents.debate.application.prompt_runtime import (
    MAX_CHAR_HISTORY as PROMPT_MAX_CHAR_HISTORY,
)
from src.agents.debate.application.prompt_runtime import (
    build_bear_round_messages,
    build_bull_round_messages,
    build_moderator_messages,
    log_debate_context,
    log_llm_config,
    log_llm_response,
    log_messages,
)
from src.agents.debate.application.report_service import get_debate_reports_text
from src.agents.debate.domain.fact_builders import (
    build_financial_facts,
    build_news_facts,
    build_technical_facts,
    render_strict_facts_registry,
    summarize_facts_by_source,
)
from src.agents.debate.domain.models import EvidenceFact, FactBundle
from src.shared.kernel.tools.logger import get_logger

logger = get_logger(__name__)

MAX_CHAR_HISTORY = PROMPT_MAX_CHAR_HISTORY


class _LLMLike(Protocol):
    async def ainvoke(self, messages: object) -> object: ...


async def extract_debate_facts(
    state: Mapping[str, object],
    *,
    source_reader: DebateSourceReaderPort,
) -> DebateFactExtractionResult:
    artifact_context = build_debate_artifact_context(state)
    ticker = artifact_context.ticker
    if ticker is None:
        raise ValueError(
            "Missing intent_extraction.resolved_ticker for fact extraction"
        )

    source_data = await source_reader.load_debate_source_data(
        financial_reports_artifact_id=artifact_context.financial_reports_artifact_id,
        news_artifact_id=artifact_context.news_artifact_id,
        technical_artifact_id=artifact_context.technical_artifact_id,
    )

    facts: list[EvidenceFact] = []
    facts.extend(
        build_financial_facts(source_data.financial_reports, start_index=len(facts) + 1)
    )
    facts.extend(build_news_facts(source_data.news_items, start_index=len(facts) + 1))
    facts.extend(
        build_technical_facts(
            source_data.technical_payload,
            ta_artifact_id=artifact_context.technical_artifact_id,
            start_index=len(facts) + 1,
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

    summary = summarize_facts_by_source(facts)
    strict_facts_registry = render_strict_facts_registry(facts)

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
    source_reader: DebateSourceReaderPort,
) -> dict[str, object]:
    conversation_context = build_debate_conversation_context(state)
    ticker = conversation_context.ticker
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for bull agent")

    log_llm_config("BULL_AGENT", round_num, llm)
    compressed_reports = await get_debate_reports_text(
        state, stage=f"bull_r{round_num}", ticker=ticker, source_reader=source_reader
    )

    system_content = system_prompt_template.format(
        ticker=ticker,
        reports=compressed_reports,
        adversarial_rule=adversarial_rule,
    )
    history = conversation_context.history
    messages, context = build_bull_round_messages(
        system_content=system_content,
        round_num=round_num,
        history=history,
    )
    if context is not None:
        my_last_arg, bear_last_arg, judge_feedback = context
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
    source_reader: DebateSourceReaderPort,
) -> dict[str, object]:
    conversation_context = build_debate_conversation_context(state)
    ticker = conversation_context.ticker
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for bear agent")

    log_llm_config("BEAR_AGENT", round_num, llm)
    compressed_reports = await get_debate_reports_text(
        state, stage=f"bear_r{round_num}", ticker=ticker, source_reader=source_reader
    )

    system_content = system_prompt_template.format(
        ticker=ticker,
        reports=compressed_reports,
        adversarial_rule=adversarial_rule,
    )
    history = conversation_context.history
    messages, context = build_bear_round_messages(
        system_content=system_content,
        round_num=round_num,
        history=history,
    )
    if context is not None:
        my_last_arg, bull_last_arg, judge_feedback = context
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
    detector: SycophancyDetectorPort,
    source_reader: DebateSourceReaderPort,
) -> dict[str, object]:
    conversation_context = build_debate_conversation_context(state)
    ticker = conversation_context.ticker
    if ticker is None:
        raise ValueError("Missing intent_extraction.resolved_ticker for moderator")

    log_llm_config("MODERATOR", round_num, llm)

    debate_map = conversation_context.debate_context
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
        state,
        stage=f"moderator_r{round_num}",
        ticker=ticker,
        source_reader=source_reader,
    )
    history = conversation_context.history

    system_content = system_prompt_template.format(
        ticker=ticker, reports=compressed_reports
    )
    if is_sycophantic:
        system_content += "\n⚠️ SYCOPHANCY DETECTED. Demand counter-arguments."

    messages = build_moderator_messages(system_content=system_content, history=history)

    log_messages(messages, "MODERATOR_CRITIQUE", round_num)
    response = await llm.ainvoke(messages)
    response_text = str(getattr(response, "content", ""))
    log_llm_response("MODERATOR_CRITIQUE", round_num, response_text)

    return {
        "history": [AIMessage(content=response_text, name="Judge")],
        "current_round": round_num,
    }
