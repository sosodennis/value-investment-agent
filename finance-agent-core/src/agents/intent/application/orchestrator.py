from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.agents.intent.domain.models import TickerCandidate
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


class _ParsedSelectionInput(Protocol):
    selected_symbol: str | None
    ticker: str | None


class _IntentExtractionLike(Protocol):
    company_name: str | None
    ticker: str | None
    is_valuation_request: bool
    reasoning: str | None

    def model_dump(self, *, mode: str = "python") -> dict[str, object]: ...


@dataclass
class IntentOrchestrator:
    extract_intent_fn: Callable[[str], _IntentExtractionLike]
    search_ticker_fn: Callable[[str], list[TickerCandidate]]
    web_search_fn: Callable[[str], str]
    extract_candidates_from_search_fn: Callable[[str, str], list[TickerCandidate]]
    deduplicate_candidates_fn: Callable[[list[TickerCandidate]], list[TickerCandidate]]
    should_request_clarification_fn: Callable[[list[TickerCandidate]], bool]
    get_company_profile_fn: Callable[[str], CompanyProfile | None]
    parse_ticker_candidates_fn: Callable[[object], list[TickerCandidate]]
    parse_resume_selection_input_fn: Callable[[object], _ParsedSelectionInput]
    summarize_preview_fn: Callable[[JSONObject], JSONObject]
    build_output_artifact_fn: Callable[[str, JSONObject], AgentOutputArtifactPayload]

    def extract_intent(self, user_query: str) -> _IntentExtractionLike:
        return self.extract_intent_fn(user_query)

    def build_search_queries(
        self,
        *,
        extracted_ticker: object,
        extracted_name: object,
        user_query: object,
    ) -> list[str]:
        queries: list[str] = []

        if isinstance(extracted_name, str) and extracted_name.strip():
            queries.append(extracted_name.strip())

        if (
            isinstance(extracted_ticker, str)
            and extracted_ticker.strip()
            and extracted_ticker.strip() not in queries
        ):
            queries.append(extracted_ticker.strip())

        if queries:
            return queries

        if isinstance(user_query, str) and user_query.strip():
            clean_query = user_query.replace("Valuate", "").replace("Value", "").strip()
            if clean_query:
                return [clean_query]

        return []

    def search_candidates(self, search_queries: list[str]) -> list[TickerCandidate]:
        candidate_map: dict[str, TickerCandidate] = {}

        for query in search_queries:
            yf_candidates = self.search_ticker_fn(query)
            for candidate in yf_candidates:
                existing = candidate_map.get(candidate.symbol)
                if existing is None or candidate.confidence > existing.confidence:
                    candidate_map[candidate.symbol] = candidate

        primary_query = search_queries[0]
        search_results = self.web_search_fn(
            f'"{primary_query}" stock ticker symbol official'
        )
        web_candidates = self.extract_candidates_from_search_fn(
            primary_query, search_results
        )
        for candidate in web_candidates:
            existing = candidate_map.get(candidate.symbol)
            if existing is None or candidate.confidence > existing.confidence:
                candidate_map[candidate.symbol] = candidate

        return self.deduplicate_candidates_fn(list(candidate_map.values()))

    def parse_candidates(self, raw_candidates: object) -> list[TickerCandidate]:
        return self.parse_ticker_candidates_fn(raw_candidates)

    def needs_clarification(self, candidates: list[TickerCandidate]) -> bool:
        return self.should_request_clarification_fn(candidates)

    def resolve_profile(self, ticker: str) -> CompanyProfile | None:
        return self.get_company_profile_fn(ticker)

    def build_resolved_intent_context(
        self, *, ticker: str, profile: CompanyProfile
    ) -> JSONObject:
        return {
            "status": "resolved",
            "resolved_ticker": ticker,
            "company_profile": profile.model_dump(),
        }

    def build_output_artifact(
        self, *, resolved_ticker: str, intent_ctx: JSONObject
    ) -> AgentOutputArtifactPayload:
        return self.build_output_artifact_fn(
            f"已確認分析標的: {resolved_ticker}",
            self.summarize_preview_fn(intent_ctx),
        )

    def resolve_selected_symbol(
        self,
        *,
        user_input: object,
        candidate_objs: list[TickerCandidate],
    ) -> str | None:
        parsed_input = self.parse_resume_selection_input_fn(user_input)
        if parsed_input.selected_symbol is not None:
            return parsed_input.selected_symbol
        if parsed_input.ticker is not None:
            return parsed_input.ticker

        if candidate_objs:
            return candidate_objs[0].symbol
        return None
