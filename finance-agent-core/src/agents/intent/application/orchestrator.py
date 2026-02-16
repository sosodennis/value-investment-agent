from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from src.agents.intent.domain.models import TickerCandidate
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_INTERRUPT_PAYLOAD,
    CONTRACT_KIND_WORKFLOW_STATE,
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject

logger = get_logger(__name__)


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
    serialize_ticker_candidates_fn: Callable[[list[TickerCandidate]], list[JSONObject]]
    serialize_ticker_selection_interrupt_payload_fn: Callable[
        [list[TickerCandidate], object], JSONObject
    ]
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

    def serialize_candidates(
        self, candidates: list[TickerCandidate]
    ) -> list[JSONObject]:
        return self.serialize_ticker_candidates_fn(candidates)

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

    def build_clarification_resolution_update(
        self,
        *,
        user_input: object,
        candidates_raw: object,
        interrupt_payload_dump: JSONObject,
    ) -> dict[str, object] | None:
        candidate_objs = self.parse_candidates(candidates_raw)
        selected_symbol = self.resolve_selected_symbol(
            user_input=user_input,
            candidate_objs=candidate_objs,
        )
        if not selected_symbol:
            return None

        profile = self.resolve_profile(selected_symbol)
        if not profile:
            return None

        from langchain_core.messages import AIMessage, HumanMessage

        intent_ctx = self.build_resolved_intent_context(
            ticker=selected_symbol,
            profile=profile,
        )
        artifact = self.build_output_artifact(
            resolved_ticker=selected_symbol,
            intent_ctx=intent_ctx,
        )
        intent_ctx["artifact"] = artifact

        return {
            "intent_extraction": intent_ctx,
            "ticker": selected_symbol,
            "messages": [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "type": "ticker_selection",
                        "data": interrupt_payload_dump,
                        "agent_id": "intent_extraction",
                    },
                ),
                HumanMessage(content=f"Selected Ticker: {selected_symbol}"),
            ],
            "current_node": "clarifying",
            "internal_progress": {"clarifying": "done"},
            "node_statuses": {"intent_extraction": "done"},
        }

    def run_extraction(self, state: Mapping[str, object]) -> IntentNodeResult:
        user_query = state.get("user_query")
        if not isinstance(user_query, str) or not user_query.strip():
            logger.warning(
                "--- Intent Extraction: No query provided, requesting clarification ---"
            )
            return IntentNodeResult(
                update={
                    "intent_extraction": {
                        "status": "clarifying",
                    },
                    "current_node": "extraction",
                    "internal_progress": {
                        "extraction": "done",
                        "clarifying": "running",
                    },
                },
                goto="clarifying",
            )

        try:
            logger.info(
                "--- Intent Extraction: Extracting intent from: %s ---", user_query
            )
            intent = self.extract_intent(user_query)
            return IntentNodeResult(
                update={
                    "intent_extraction": {
                        "extracted_intent": intent.model_dump(mode="json"),
                        "status": "searching",
                    },
                    "current_node": "extraction",
                    "internal_progress": {"extraction": "done", "searching": "running"},
                    "node_statuses": {"intent_extraction": "running"},
                },
                goto="searching",
            )
        except Exception as exc:
            logger.error("Intent extraction failed: %s", exc)
            return IntentNodeResult(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "extraction",
                    "internal_progress": {
                        "extraction": "error",
                        "clarifying": "running",
                    },
                    "node_statuses": {"intent_extraction": "degraded"},
                    "error_logs": [
                        {
                            "node": "extraction",
                            "error": f"Model failed to extract intent: {str(exc)}",
                            "severity": "error",
                        }
                    ],
                },
                goto="clarifying",
            )

    def run_searching(self, state: Mapping[str, object]) -> IntentNodeResult:
        intent_ctx_raw = state.get("intent_extraction")
        intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
        intent_raw = intent_ctx.get("extracted_intent")
        intent = intent_raw if isinstance(intent_raw, Mapping) else {}
        search_queries = self.build_search_queries(
            extracted_ticker=intent.get("ticker"),
            extracted_name=intent.get("company_name"),
            user_query=state.get("user_query"),
        )
        if not search_queries:
            logger.warning(
                "--- Intent Extraction: Search query missing, requesting clarification ---"
            )
            return IntentNodeResult(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "searching",
                    "internal_progress": {"searching": "done", "clarifying": "running"},
                },
                goto="clarifying",
            )

        try:
            logger.info(
                "--- Intent Extraction: Searching for queries: %s ---", search_queries
            )
            final_candidates = self.search_candidates(search_queries)
            logger.info(
                "Final candidates: %s",
                [candidate.symbol for candidate in final_candidates],
            )
            log_boundary_event(
                logger,
                node="intent.searching",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_WORKFLOW_STATE,
                error_code="OK",
                state=state,
                detail={
                    "candidate_count": len(final_candidates),
                    "candidate_symbols": [
                        candidate.symbol for candidate in final_candidates
                    ],
                },
            )
            return IntentNodeResult(
                update={
                    "intent_extraction": {
                        "ticker_candidates": self.serialize_candidates(
                            final_candidates
                        ),
                        "status": "deciding",
                    },
                    "current_node": "searching",
                    "internal_progress": {"searching": "done", "deciding": "running"},
                },
                goto="deciding",
            )
        except Exception as exc:
            log_boundary_event(
                logger,
                node="intent.searching",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_WORKFLOW_STATE,
                error_code="INTENT_SEARCH_FAILED",
                state=state,
                detail={"exception": str(exc)},
                level=logging.ERROR,
            )
            logger.error("Ticker search failed: %s", exc)
            return IntentNodeResult(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "searching",
                    "internal_progress": {
                        "searching": "error",
                        "clarifying": "running",
                    },
                    "node_statuses": {"intent_extraction": "degraded"},
                    "error_logs": [
                        {
                            "node": "searching",
                            "error": (
                                "Search tool failed: "
                                f"{str(exc)}. Switching to manual selection."
                            ),
                            "severity": "error",
                            "error_code": "INTENT_SEARCH_FAILED",
                            "contract_kind": CONTRACT_KIND_WORKFLOW_STATE,
                            "artifact_id": None,
                            "diagnostics": build_replay_diagnostics(
                                state, node="intent.searching"
                            ),
                        }
                    ],
                },
                goto="clarifying",
            )

    def run_decision(self, state: Mapping[str, object]) -> IntentNodeResult:
        intent_ctx_raw = state.get("intent_extraction")
        intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
        candidates = intent_ctx.get("ticker_candidates") or []
        if not isinstance(candidates, list) or not candidates:
            logger.warning(
                "--- Intent Extraction: No candidates found, requesting clarification ---"
            )
            return IntentNodeResult(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "deciding",
                    "internal_progress": {"deciding": "done", "clarifying": "running"},
                },
                goto="clarifying",
            )

        try:
            candidate_objs = self.parse_candidates(candidates)
            if self.needs_clarification(candidate_objs):
                log_boundary_event(
                    logger,
                    node="intent.deciding",
                    artifact_id=None,
                    contract_kind=CONTRACT_KIND_INTERRUPT_PAYLOAD,
                    error_code="INTENT_TICKER_AMBIGUOUS",
                    state=state,
                    detail={
                        "candidate_count": len(candidate_objs),
                        "candidate_symbols": [
                            candidate.symbol for candidate in candidate_objs
                        ],
                    },
                )
                logger.warning(
                    "--- Intent Extraction: Ambiguity detected, requesting clarification ---"
                )
                return IntentNodeResult(
                    update={
                        "intent_extraction": {"status": "clarifying"},
                        "current_node": "deciding",
                        "internal_progress": {
                            "deciding": "done",
                            "clarifying": "running",
                        },
                    },
                    goto="clarifying",
                )

            resolved_ticker = candidate_objs[0].symbol
            logger.info(
                "--- Intent Extraction: Ticker resolved to %s ---", resolved_ticker
            )
            profile = self.resolve_profile(resolved_ticker)
            if not profile:
                logger.warning(
                    "--- Intent Extraction: Could not fetch profile for %s, requesting clarification ---",
                    resolved_ticker,
                )
                return IntentNodeResult(
                    update={
                        "intent_extraction": {"status": "clarifying"},
                        "current_node": "deciding",
                        "internal_progress": {
                            "deciding": "done",
                            "clarifying": "running",
                        },
                    },
                    goto="clarifying",
                )

            resolved_ctx = self.build_resolved_intent_context(
                ticker=resolved_ticker,
                profile=profile,
            )
            artifact = self.build_output_artifact(
                resolved_ticker=resolved_ticker,
                intent_ctx=resolved_ctx,
            )
            resolved_ctx["artifact"] = artifact

            return IntentNodeResult(
                update={
                    "intent_extraction": resolved_ctx,
                    "ticker": resolved_ticker,
                    "current_node": "deciding",
                    "internal_progress": {"deciding": "done"},
                    "node_statuses": {"intent_extraction": "done"},
                },
                goto="END",
            )
        except Exception as exc:
            log_boundary_event(
                logger,
                node="intent.deciding",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_WORKFLOW_STATE,
                error_code="INTENT_DECISION_FAILED",
                state=state,
                detail={"exception": str(exc)},
                level=logging.ERROR,
            )
            logger.error("Decision logic failed: %s", exc)
            return IntentNodeResult(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "deciding",
                    "internal_progress": {"deciding": "error", "clarifying": "running"},
                    "node_statuses": {"intent_extraction": "degraded"},
                    "error_logs": [
                        {
                            "node": "deciding",
                            "error": (
                                "Decision logic crashed: "
                                f"{str(exc)}. Switching to manual selection."
                            ),
                            "severity": "error",
                            "error_code": "INTENT_DECISION_FAILED",
                            "contract_kind": CONTRACT_KIND_WORKFLOW_STATE,
                            "artifact_id": None,
                            "diagnostics": build_replay_diagnostics(
                                state, node="intent.deciding"
                            ),
                        }
                    ],
                },
                goto="clarifying",
            )

    def build_clarification_interrupt_payload(
        self, state: Mapping[str, object]
    ) -> tuple[JSONObject, object]:
        intent_ctx_raw = state.get("intent_extraction")
        intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
        candidates_raw = intent_ctx.get("ticker_candidates") or []
        candidate_objs = self.parse_candidates(candidates_raw)
        payload = self.serialize_ticker_selection_interrupt_payload_fn(
            candidate_objs,
            intent_ctx.get("extracted_intent"),
        )
        log_boundary_event(
            logger,
            node="intent.clarifying",
            artifact_id=None,
            contract_kind=CONTRACT_KIND_INTERRUPT_PAYLOAD,
            error_code="INTENT_SELECTION_INTERRUPT_PREPARED",
            state=state,
            detail={
                "candidate_count": len(candidate_objs),
                "candidate_symbols": [candidate.symbol for candidate in candidate_objs],
            },
        )
        return payload, candidates_raw

    def build_clarification_retry_update(self) -> IntentNodeResult:
        return IntentNodeResult(
            update={
                "intent_extraction": {"status": "extraction"},
                "current_node": "clarifying",
                "internal_progress": {"clarifying": "done", "extraction": "running"},
            },
            goto="extraction",
        )


@dataclass(frozen=True)
class IntentNodeResult:
    update: dict[str, object]
    goto: str
