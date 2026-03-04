from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.debate.application.debate_context import build_debate_artifact_context
from src.agents.debate.application.dto import DebateSourceData, DebateSourceLoadIssue
from src.agents.debate.application.ports import DebateSourceReaderPort
from src.agents.debate.application.prompt_runtime import (
    compress_reports,
    hash_text,
)
from src.agents.debate.interface.serializers import (
    build_compressed_report_payload as serialize_compressed_report_payload,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)
_MISSING_FACTS_REGISTRY_TEXT = (
    "FACTS_REGISTRY (STRICT CITATION REQUIRED):\n"
    "[NO_FACTS_AVAILABLE] Evidence registry unavailable."
)


@dataclass(frozen=True)
class PreparedDebateReports:
    payload: JSONObject
    load_issues: list[DebateSourceLoadIssue]

    @property
    def is_degraded(self) -> bool:
        return bool(self.load_issues)

    @property
    def degraded_reason_codes(self) -> list[str]:
        return [issue.reason_code for issue in self.load_issues]


@dataclass(frozen=True)
class DebatePromptContextText:
    facts_registry_text: str
    context_summary_text: str


def build_compressed_report_payload(
    *,
    ticker: str | None,
    source_data: DebateSourceData,
    news_artifact_id: str | None,
    technical_artifact_id: str | None,
) -> JSONObject:
    log_event(
        logger,
        event="debate_report_input_built",
        message="debate report input built",
        fields={
            "ticker": ticker or "unknown",
            "financials_count": len(source_data.financial_reports),
            "news_items_count": len(source_data.news_items),
            "ta_present": source_data.technical_payload is not None,
            "news_artifact_id": news_artifact_id or "none",
            "ta_artifact_id": technical_artifact_id or "none",
            "is_degraded": source_data.is_degraded,
            "degraded_reason_count": len(source_data.load_issues),
            "degraded_reasons": [
                issue.reason_code for issue in source_data.load_issues
            ],
        },
    )

    return serialize_compressed_report_payload(
        ticker=ticker,
        source_data=source_data,
    )


async def prepare_debate_reports(
    state: Mapping[str, object],
    *,
    source_reader: DebateSourceReaderPort,
) -> PreparedDebateReports:
    artifact_context = build_debate_artifact_context(state)
    source_data = await source_reader.load_debate_source_data(
        financial_reports_artifact_id=artifact_context.financial_reports_artifact_id,
        news_artifact_id=artifact_context.news_artifact_id,
        technical_artifact_id=artifact_context.technical_artifact_id,
    )
    payload = build_compressed_report_payload(
        ticker=artifact_context.ticker,
        source_data=source_data,
        news_artifact_id=artifact_context.news_artifact_id,
        technical_artifact_id=artifact_context.technical_artifact_id,
    )
    return PreparedDebateReports(
        payload=payload,
        load_issues=source_data.load_issues,
    )


async def get_debate_prompt_context_text(
    state: Mapping[str, object],
    *,
    stage: str,
    ticker: str,
    source_reader: DebateSourceReaderPort,
) -> DebatePromptContextText:
    artifact_context = build_debate_artifact_context(state)
    if artifact_context.cached_context_summary_text is not None:
        log_event(
            logger,
            event="debate_context_summary_text_resolved",
            message="debate context summary text resolved",
            fields={
                "stage": stage,
                "ticker": ticker,
                "source": "cached",
                "chars": len(artifact_context.cached_context_summary_text),
                "hash": hash_text(artifact_context.cached_context_summary_text),
            },
        )
        context_summary_text = artifact_context.cached_context_summary_text
    else:
        prepared = await prepare_debate_reports(state, source_reader=source_reader)
        if prepared.is_degraded:
            log_event(
                logger,
                event="debate_reports_source_degraded",
                message="debate reports source degraded",
                level=logging.WARNING,
                error_code="DEBATE_REPORTS_SOURCE_DEGRADED",
                fields={
                    "stage": stage,
                    "ticker": ticker,
                    "degraded_reason_count": len(prepared.load_issues),
                    "degraded_reasons": prepared.degraded_reason_codes,
                },
            )
        context_summary_text = compress_reports(prepared.payload)
        log_event(
            logger,
            event="debate_context_summary_text_resolved",
            message="debate context summary text resolved",
            fields={
                "stage": stage,
                "ticker": ticker,
                "source": "computed",
                "chars": len(context_summary_text),
                "hash": hash_text(context_summary_text),
            },
        )

    if artifact_context.cached_facts_registry_text is not None:
        facts_registry_text = artifact_context.cached_facts_registry_text
        log_event(
            logger,
            event="debate_facts_registry_text_resolved",
            message="debate facts registry text resolved",
            fields={
                "stage": stage,
                "ticker": ticker,
                "source": "cached",
                "chars": len(facts_registry_text),
                "hash": hash_text(facts_registry_text),
            },
        )
    else:
        facts_registry_text = _MISSING_FACTS_REGISTRY_TEXT
        log_event(
            logger,
            event="debate_facts_registry_missing",
            message="debate facts registry text missing; using placeholder",
            level=logging.WARNING,
            error_code="DEBATE_FACTS_REGISTRY_MISSING",
            fields={
                "stage": stage,
                "ticker": ticker,
                "source": "placeholder",
                "chars": len(facts_registry_text),
                "hash": hash_text(facts_registry_text),
            },
        )

    log_event(
        logger,
        event="debate_prompt_context_resolved",
        message="debate prompt context resolved",
        fields={
            "stage": stage,
            "ticker": ticker,
            "facts_registry_chars": len(facts_registry_text),
            "context_summary_chars": len(context_summary_text),
        },
    )
    return DebatePromptContextText(
        facts_registry_text=facts_registry_text,
        context_summary_text=context_summary_text,
    )
