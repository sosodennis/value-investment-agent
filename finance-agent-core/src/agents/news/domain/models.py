from __future__ import annotations

from dataclasses import dataclass

from src.common.types import JSONObject


@dataclass(frozen=True)
class NewsAggregationResult:
    sentiment_label: str
    weighted_score: float
    key_themes: list[str]
    summary_text: str
    report_payload: JSONObject
    top_headlines: list[str]
