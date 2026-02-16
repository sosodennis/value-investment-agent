from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.domain.services import (
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
)
from src.agents.debate.interface.contracts import parse_debate_artifact_model
from src.shared.kernel.types import JSONObject


class HistoryMessageLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class DebateSourceDataLike(Protocol):
    financial_reports: list[JSONObject]
    news_items: list[JSONObject]
    technical_payload: JSONObject | None


def build_compressed_report_payload(
    *,
    ticker: str | None,
    source_data: DebateSourceDataLike,
) -> JSONObject:
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


def build_final_report_payload(
    *,
    conclusion_data: Mapping[str, object],
    valid_facts: list[EvidenceFact],
    history: list[HistoryMessageLike],
) -> JSONObject:
    return parse_debate_artifact_model(
        {
            **conclusion_data,
            "facts": [fact.model_dump(mode="json") for fact in valid_facts],
            "history": [msg.model_dump(mode="json") for msg in history],
        }
    )
