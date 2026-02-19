from __future__ import annotations

from collections.abc import Mapping

from src.agents.debate.application.debate_context import build_debate_artifact_context
from src.agents.debate.application.dto import DebateSourceData
from src.agents.debate.application.ports import DebateSourceReaderPort
from src.agents.debate.application.prompt_runtime import (
    compress_reports,
    hash_text,
)
from src.agents.debate.interface.serializers import (
    build_compressed_report_payload as serialize_compressed_report_payload,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


def build_compressed_report_payload(
    *,
    ticker: str | None,
    source_data: DebateSourceData,
    news_artifact_id: str | None,
    technical_artifact_id: str | None,
) -> dict[str, object]:
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
) -> dict[str, object]:
    artifact_context = build_debate_artifact_context(state)
    source_data = await source_reader.load_debate_source_data(
        financial_reports_artifact_id=artifact_context.financial_reports_artifact_id,
        news_artifact_id=artifact_context.news_artifact_id,
        technical_artifact_id=artifact_context.technical_artifact_id,
    )
    return build_compressed_report_payload(
        ticker=artifact_context.ticker,
        source_data=source_data,
        news_artifact_id=artifact_context.news_artifact_id,
        technical_artifact_id=artifact_context.technical_artifact_id,
    )


async def get_debate_reports_text(
    state: Mapping[str, object],
    *,
    stage: str,
    ticker: str,
    source_reader: DebateSourceReaderPort,
) -> str:
    artifact_context = build_debate_artifact_context(state)
    if artifact_context.cached_reports is not None:
        log_event(
            logger,
            event="debate_reports_compressed",
            message="debate reports compressed",
            fields={
                "stage": stage,
                "ticker": ticker,
                "source": "cached",
                "chars": len(artifact_context.cached_reports),
                "hash": hash_text(artifact_context.cached_reports),
            },
        )
        return artifact_context.cached_reports

    reports = await prepare_debate_reports(state, source_reader=source_reader)
    compressed_reports = compress_reports(reports)
    log_event(
        logger,
        event="debate_reports_compressed",
        message="debate reports compressed",
        fields={
            "stage": stage,
            "ticker": ticker,
            "source": "computed",
            "chars": len(compressed_reports),
            "hash": hash_text(compressed_reports),
        },
    )
    return compressed_reports
