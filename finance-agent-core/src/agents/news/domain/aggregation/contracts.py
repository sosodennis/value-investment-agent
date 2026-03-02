from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsAggregationResult:
    sentiment_label: str
    weighted_score: float
    key_themes: list[str]
    summary_text: str
    top_headlines: list[str]
