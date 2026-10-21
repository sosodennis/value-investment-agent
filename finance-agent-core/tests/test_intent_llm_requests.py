from __future__ import annotations

from pydantic import BaseModel

from src.agents.intent.application.intent_extraction_service import (
    extract_candidates_from_search,
    extract_intent,
)
from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.contracts import (
    IntentExtraction,
    SearchExtraction,
    TickerCandidateModel,
)
from src.shared.llm.contracts import ModelRoute, StructuredRequest


class _FakeProvider:
    def __init__(self, response: BaseModel | None = None) -> None:
        self.response = response
        self.requests: list[StructuredRequest[BaseModel]] = []

    def complete_structured(self, request: StructuredRequest[BaseModel]) -> BaseModel:
        self.requests.append(request)
        if self.response is None:
            raise RuntimeError("provider unavailable")
        return self.response


def _route() -> ModelRoute:
    return ModelRoute(alias="openrouter-default")


def test_extract_intent_sends_typed_structured_request() -> None:
    expected = IntentExtraction(
        company_name="Apple Inc.", ticker="AAPL", is_valuation_request=True
    )
    provider = _FakeProvider(expected)

    result = extract_intent(
        "Value Apple",
        intent_model_type=IntentExtraction,
        llm_provider=provider,  # type: ignore[arg-type]
        llm_route=_route(),
    )

    request = provider.requests[0]
    assert result is expected
    assert request.completion.operation == "intent.extract"
    assert request.completion.route == _route()
    assert request.completion.timeout_seconds == 30.0
    assert request.completion.messages[0].role.value == "system"
    assert request.completion.messages[1].content == "Value Apple"
    assert request.response_schema is IntentExtraction


def test_extract_intent_keeps_heuristic_fallback_on_provider_failure() -> None:
    provider = _FakeProvider()

    result = extract_intent(
        "Value Apple",
        intent_model_type=IntentExtraction,
        llm_provider=provider,  # type: ignore[arg-type]
        llm_route=_route(),
    )

    assert result.company_name == "Apple"
    assert len(provider.requests) == 1


def test_extract_search_candidates_sends_typed_structured_request() -> None:
    candidate = TickerCandidateModel(
        symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", confidence=0.99
    )
    provider = _FakeProvider(SearchExtraction(candidates=[candidate]))

    results = extract_candidates_from_search(
        "Apple",
        "Apple trades on NASDAQ as AAPL.",
        search_extraction_model_type=SearchExtraction,
        to_ticker_candidate_fn=lambda value: TickerCandidate(
            symbol=value.symbol,
            name=value.name,
            exchange=value.exchange,
            type=value.type,
            confidence=value.confidence,
        ),
        llm_provider=provider,  # type: ignore[arg-type]
        llm_route=_route(),
    )

    request = provider.requests[0]
    assert len(results) == 1
    assert results[0].symbol == "AAPL"
    assert request.completion.operation == "intent.search_extraction"
    assert "Apple" in request.completion.messages[1].content
    assert "NASDAQ" in request.completion.messages[1].content
    assert request.response_schema is SearchExtraction
