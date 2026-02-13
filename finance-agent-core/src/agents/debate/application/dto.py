from __future__ import annotations

from dataclasses import dataclass

from src.agents.debate.domain.models import EvidenceFact
from src.common.types import JSONObject


@dataclass(frozen=True)
class DebateFactExtractionResult:
    ticker: str
    facts: list[EvidenceFact]
    facts_hash: str
    summary: dict[str, int]
    bundle_payload: JSONObject
    strict_facts_registry: str
