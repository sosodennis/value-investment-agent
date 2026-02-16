from __future__ import annotations

from src.agents.intent.application.intent_service import (
    deduplicate_candidates,
    extract_candidates_from_search,
    extract_intent,
)
from src.agents.intent.application.orchestrator import IntentOrchestrator
from src.agents.intent.data.market_clients import (
    get_company_profile,
    search_ticker,
    web_search,
)
from src.agents.intent.domain.policies import should_request_clarification
from src.agents.intent.interface.contracts import IntentExtraction, SearchExtraction
from src.agents.intent.interface.mappers import (
    summarize_intent_for_preview,
    to_ticker_candidate,
)
from src.agents.intent.interface.parsers import (
    parse_resume_selection_input,
    parse_ticker_candidates,
)
from src.agents.intent.interface.serializers import (
    serialize_ticker_candidates,
    serialize_ticker_selection_interrupt_payload,
)
from src.interface.events.schemas import build_artifact_payload
from src.shared.kernel.contracts import OUTPUT_KIND_INTENT_EXTRACTION


def _build_intent_output_artifact(
    summary: str, preview: dict[str, object]
) -> dict[str, object]:
    return build_artifact_payload(
        kind=OUTPUT_KIND_INTENT_EXTRACTION,
        summary=summary,
        preview=preview,
        reference=None,
    )


def build_intent_orchestrator() -> IntentOrchestrator:
    return IntentOrchestrator(
        extract_intent_fn=lambda query: extract_intent(
            query, intent_model_type=IntentExtraction
        ),
        search_ticker_fn=search_ticker,
        web_search_fn=web_search,
        extract_candidates_from_search_fn=lambda query,
        search_results: extract_candidates_from_search(
            query,
            search_results,
            search_extraction_model_type=SearchExtraction,
            to_ticker_candidate_fn=to_ticker_candidate,
        ),
        deduplicate_candidates_fn=deduplicate_candidates,
        should_request_clarification_fn=should_request_clarification,
        get_company_profile_fn=get_company_profile,
        parse_ticker_candidates_fn=parse_ticker_candidates,
        serialize_ticker_candidates_fn=serialize_ticker_candidates,
        serialize_ticker_selection_interrupt_payload_fn=(
            lambda candidates,
            extracted_intent: serialize_ticker_selection_interrupt_payload(
                candidates=candidates,
                extracted_intent=extracted_intent,
            )
        ),
        parse_resume_selection_input_fn=parse_resume_selection_input,
        summarize_preview_fn=summarize_intent_for_preview,
        build_output_artifact_fn=_build_intent_output_artifact,
    )


intent_orchestrator = build_intent_orchestrator()
