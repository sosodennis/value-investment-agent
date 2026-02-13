from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.agents.intent.application.use_cases import (
    deduplicate_candidates,
    extract_candidates_from_search,
    extract_intent,
)
from src.agents.intent.data.market_clients import (
    get_company_profile,
    search_ticker,
    web_search,
)
from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.domain.policies import should_request_clarification
from src.agents.intent.interface.contracts import IntentExtraction
from src.agents.intent.interface.mappers import summarize_intent_for_preview
from src.agents.intent.interface.parsers import (
    parse_resume_selection_input,
    parse_ticker_candidates,
)
from src.common.contracts import OUTPUT_KIND_INTENT_EXTRACTION
from src.common.types import AgentOutputArtifactPayload, JSONObject
from src.interface.schemas import build_artifact_payload
from src.shared.domain.market_identity import CompanyProfile


@dataclass
class IntentOrchestrator:
    extract_intent_fn: Callable[[str], IntentExtraction]
    search_ticker_fn: Callable[[str], list[TickerCandidate]]
    web_search_fn: Callable[[str], str]
    extract_candidates_from_search_fn: Callable[[str, str], list[TickerCandidate]]
    deduplicate_candidates_fn: Callable[[list[TickerCandidate]], list[TickerCandidate]]
    should_request_clarification_fn: Callable[[list[TickerCandidate]], bool]
    get_company_profile_fn: Callable[[str], CompanyProfile | None]
    summarize_preview_fn: Callable[[JSONObject], JSONObject]

    def extract_intent(self, user_query: str) -> IntentExtraction:
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
        return parse_ticker_candidates(raw_candidates)

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
        summary = f"已確認分析標的: {resolved_ticker}"
        return build_artifact_payload(
            kind=OUTPUT_KIND_INTENT_EXTRACTION,
            summary=summary,
            preview=self.summarize_preview_fn(intent_ctx),
            reference=None,
        )

    def resolve_selected_symbol(
        self,
        *,
        user_input: object,
        candidate_objs: list[TickerCandidate],
    ) -> str | None:
        parsed_input = parse_resume_selection_input(user_input)
        if parsed_input.selected_symbol is not None:
            return parsed_input.selected_symbol
        if parsed_input.ticker is not None:
            return parsed_input.ticker

        if candidate_objs:
            return candidate_objs[0].symbol
        return None


intent_orchestrator = IntentOrchestrator(
    extract_intent_fn=extract_intent,
    search_ticker_fn=search_ticker,
    web_search_fn=web_search,
    extract_candidates_from_search_fn=extract_candidates_from_search,
    deduplicate_candidates_fn=deduplicate_candidates,
    should_request_clarification_fn=should_request_clarification,
    get_company_profile_fn=get_company_profile,
    summarize_preview_fn=summarize_intent_for_preview,
)
