from __future__ import annotations

from typing import Protocol

from src.agents.debate.domain.entities import EvidenceFact
from src.shared.kernel.types import JSONObject


class HistoryMessageLike(Protocol):
    name: str | None
    content: object


class _CitationValidatorLike(Protocol):
    def __call__(self, text: str, facts: list[EvidenceFact]) -> object: ...


def build_verdict_history_text(history: list[HistoryMessageLike]) -> str:
    return "\n\n".join(
        [f"{message.name or 'Agent'}: {message.content}" for message in history]
    )


def _build_role_transcript(history: list[HistoryMessageLike], role_name: str) -> str:
    messages = [
        str(message.content) for message in history if message.name == role_name
    ]
    return "\n".join(messages)


def build_citation_audit_payload(
    *,
    history: list[HistoryMessageLike],
    valid_facts: list[EvidenceFact],
    validate_citations_fn: _CitationValidatorLike,
) -> JSONObject:
    bull_transcript = _build_role_transcript(history, "GrowthHunter")
    bear_transcript = _build_role_transcript(history, "ForensicAccountant")
    return {
        "bull": validate_citations_fn(bull_transcript, valid_facts),
        "bear": validate_citations_fn(bear_transcript, valid_facts),
    }
