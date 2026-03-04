from __future__ import annotations

from typing import Protocol

from src.agents.debate.application.dto import DebateSourceData
from src.interface.artifacts.artifact_data_models import DebateFactsArtifactData
from src.shared.kernel.types import JSONObject


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


class DebateArtifactRepositoryPort(Protocol):
    async def save_facts_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_facts_bundle(
        self,
        artifact_id: str,
    ) -> DebateFactsArtifactData | None: ...

    async def save_final_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...
