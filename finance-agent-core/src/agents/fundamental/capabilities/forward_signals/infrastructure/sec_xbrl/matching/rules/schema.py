from __future__ import annotations

from pydantic import BaseModel, Field


class SignalLexiconEntry(BaseModel):
    aliases: list[str] = Field(default_factory=list)


class LexiconConfig(BaseModel):
    version: int = 1
    extends: str | None = None
    forward_cues: list[str] = Field(default_factory=list)
    signals: dict[str, SignalLexiconEntry] = Field(default_factory=dict)


class MetricPatternRule(BaseModel):
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    forward_only: bool = True


class PatternCatalogConfig(BaseModel):
    version: int = 1
    metrics: dict[str, MetricPatternRule] = Field(default_factory=dict)
