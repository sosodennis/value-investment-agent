from __future__ import annotations

from typing import Protocol

from src.agents.debate.application.dto import DebateSourceData


class SycophancyDetectorPort(Protocol):
    def check_consensus(
        self, bull_thesis: str, bear_thesis: str, threshold: float = 0.8
    ) -> tuple[float, bool]: ...


class DebateSourceReaderPort(Protocol):
    async def load_debate_source_data(
        self,
        *,
        financial_reports_artifact_id: str | None,
        news_artifact_id: str | None,
        technical_artifact_id: str | None,
    ) -> DebateSourceData: ...
