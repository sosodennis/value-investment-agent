from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.agents.debate.domain.models import EvidenceFact
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class DebateFactExtractionResult:
    ticker: str
    facts: list[EvidenceFact]
    facts_hash: str
    summary: dict[str, int]
    bundle_payload: JSONObject
    strict_facts_registry: str


DebateSourceArtifactKey = Literal["financial_reports", "news", "technical_analysis"]
DebateSourceLoadStatus = Literal[
    "missing_artifact_id",
    "artifact_not_found",
    "empty_payload",
]


@dataclass(frozen=True)
class DebateSourceLoadIssue:
    artifact: DebateSourceArtifactKey
    status: DebateSourceLoadStatus
    artifact_id: str | None

    @property
    def reason_code(self) -> str:
        return f"{self.artifact}:{self.status}"


@dataclass(frozen=True)
class DebateSourceData:
    financial_reports: list[JSONObject]
    news_items: list[JSONObject]
    technical_payload: JSONObject | None
    load_issues: list[DebateSourceLoadIssue]

    @property
    def is_degraded(self) -> bool:
        return bool(self.load_issues)
