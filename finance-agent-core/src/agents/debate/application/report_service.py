from __future__ import annotations

from collections.abc import Mapping

from src.agents.debate.application.debate_context import build_debate_artifact_context
from src.agents.debate.application.prompt_runtime import (
    compress_reports,
    log_compressed_reports,
)
from src.agents.debate.data.report_reader import (
    DebateSourceData,
    load_debate_source_data,
)
from src.agents.debate.domain.services import (
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
)
from src.common.tools.logger import get_logger

logger = get_logger(__name__)


def build_compressed_report_payload(
    *,
    ticker: str | None,
    source_data: DebateSourceData,
    news_artifact_id: str | None,
    technical_artifact_id: str | None,
) -> dict[str, object]:
    logger.info(
        "DEBATE_REPORT_INPUT ticker=%s financials=%d news_items=%d ta_present=%s news_artifact_id=%s ta_artifact_id=%s",
        ticker or "unknown",
        len(source_data.financial_reports),
        len(source_data.news_items),
        source_data.technical_payload is not None,
        news_artifact_id or "none",
        technical_artifact_id or "none",
    )

    return {
        "financials": {
            "data": compress_financial_data(source_data.financial_reports),
            "source_weight": "HIGH",
            "rationale": "Primary source: SEC XBRL filings (audited, regulatory-grade data)",
        },
        "news": {
            "data": compress_news_data({"news_items": source_data.news_items}),
            "source_weight": "MEDIUM",
            "rationale": "Secondary source: Curated financial news (editorial bias possible)",
        },
        "technical_analysis": {
            "data": compress_ta_data(source_data.technical_payload),
            "source_weight": "HIGH",
            "rationale": "Quantitative source: Fractional differentiation analysis (statistical signals)",
        },
        "ticker": ticker,
    }


async def prepare_debate_reports(state: Mapping[str, object]) -> dict[str, object]:
    artifact_context = build_debate_artifact_context(state)
    source_data = await load_debate_source_data(
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
    state: Mapping[str, object], *, stage: str, ticker: str
) -> str:
    artifact_context = build_debate_artifact_context(state)
    if artifact_context.cached_reports is not None:
        log_compressed_reports(stage, ticker, artifact_context.cached_reports, "cached")
        return artifact_context.cached_reports

    reports = await prepare_debate_reports(state)
    compressed_reports = compress_reports(reports)
    log_compressed_reports(stage, ticker, compressed_reports, "computed")
    return compressed_reports
