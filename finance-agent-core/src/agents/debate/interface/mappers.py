from __future__ import annotations

from typing import Protocol

from src.agents.debate.application.view_models import derive_debate_preview_view_model
from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.interface.formatters import format_debate_preview
from src.shared.kernel.types import JSONObject


def summarize_debate_for_preview(ctx: JSONObject) -> JSONObject:
    view_model = derive_debate_preview_view_model(ctx)
    return format_debate_preview(view_model)


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


def build_debate_success_update(
    *,
    conclusion_data: JSONObject,
    report_id: str | None,
    artifact: JSONObject | None,
) -> dict[str, object]:
    update: dict[str, object] = {
        "status": "success",
        "final_verdict": conclusion_data.get("decision")
        or conclusion_data.get("final_verdict"),
        "kelly_confidence": conclusion_data.get("kelly_confidence"),
        "winning_thesis": conclusion_data.get("winning_thesis"),
        "primary_catalyst": conclusion_data.get("primary_catalyst"),
        "primary_risk": conclusion_data.get("primary_risk"),
        "report_id": report_id,
        "current_round": 3,
    }
    if artifact is not None:
        update["artifact"] = artifact
    return update
