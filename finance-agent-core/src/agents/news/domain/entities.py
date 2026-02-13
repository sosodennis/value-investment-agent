from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceEntity:
    reliability_score: float


@dataclass(frozen=True)
class AnalysisEntity:
    sentiment_score: float
    summary: str
    key_event: str | None
    key_facts_count: int


@dataclass(frozen=True)
class NewsItemEntity:
    title: str | None
    source: SourceEntity | None
    analysis: AnalysisEntity | None
