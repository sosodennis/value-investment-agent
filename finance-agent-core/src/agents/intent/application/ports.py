from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.shared.cross_agent.domain.market_identity import CompanyProfile


class IIntentStructuredChain(Protocol):
    def invoke(self, payload: dict[str, str]) -> object: ...


class IIntentStructuredOutputModel(Protocol):
    def with_structured_output(
        self, schema: type[object]
    ) -> IIntentStructuredChain: ...


class IIntentLlmProvider(Protocol):
    def __call__(self, timeout: int) -> IIntentStructuredOutputModel: ...


class IIntentTickerSearchProvider(Protocol):
    def __call__(self, query: str) -> IntentTickerSearchResult: ...


@dataclass(frozen=True)
class IntentTickerSearchResult:
    candidates: list[TickerCandidate]
    failure_code: str | None = None
    failure_reason: str | None = None
    fallback_mode: str | None = None


@dataclass(frozen=True)
class IntentWebSearchResult:
    content: str
    failure_code: str | None = None
    failure_reason: str | None = None
    fallback_mode: str | None = None


class IIntentWebSearchProvider(Protocol):
    def __call__(self, query: str) -> IntentWebSearchResult: ...


class IIntentCompanyProfileProvider(Protocol):
    def __call__(self, ticker: str) -> IntentCompanyProfileLookup: ...


@dataclass(frozen=True)
class IntentCompanyProfileLookup:
    profile: CompanyProfile | None
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class IntentRuntimePorts:
    llm_provider: IIntentLlmProvider
    search_ticker: IIntentTickerSearchProvider
    web_search: IIntentWebSearchProvider
    company_profile: IIntentCompanyProfileProvider
