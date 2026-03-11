from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.intent.application.intent_extraction_service import (
    extract_candidates_from_search as extract_candidates_from_search_service,
)
from src.agents.intent.application.intent_extraction_service import (
    extract_intent as extract_intent_service,
)
from src.agents.intent.application.ports import (
    IntentCompanyProfileLookup,
    IntentRuntimePorts,
)
from src.agents.intent.domain.candidate_deduplication_policy import (
    deduplicate_candidates,
)
from src.agents.intent.domain.clarification_policy import should_request_clarification
from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.contracts import IntentExtraction, SearchExtraction
from src.agents.intent.interface.intent_preview_projection_service import (
    summarize_intent_for_preview,
)
from src.agents.intent.interface.parsers import (
    parse_resume_selection_input,
    parse_ticker_candidates,
)
from src.agents.intent.interface.serializers import (
    serialize_ticker_candidates,
    serialize_ticker_selection_interrupt_payload,
)
from src.agents.intent.interface.ticker_candidate_mapper import to_ticker_candidate
from src.interface.events.schemas import build_artifact_payload
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.contracts import OUTPUT_KIND_INTENT_EXTRACTION
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_INTERRUPT_PAYLOAD,
    CONTRACT_KIND_WORKFLOW_STATE,
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class _SearchCandidatesOutcome:
    candidates: list[TickerCandidate]
    is_degraded: bool
    degrade_error_code: str | None = None
    degrade_reason: str | None = None
    fallback_mode: str | None = None


@dataclass
class IntentOrchestrator:
    runtime_ports: IntentRuntimePorts

    def extract_intent(self, user_query: str) -> IntentExtraction:
        return extract_intent_service(
            user_query,
            intent_model_type=IntentExtraction,
            llm_provider_fn=self.runtime_ports.llm_provider,
        )

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

    def search_candidates(self, search_queries: list[str]) -> _SearchCandidatesOutcome:
        candidate_map: dict[str, TickerCandidate] = {}

        for query in search_queries:
            yf_candidates = self.runtime_ports.search_ticker(query)
            for candidate in yf_candidates:
                existing = candidate_map.get(candidate.symbol)
                if existing is None or candidate.confidence > existing.confidence:
                    candidate_map[candidate.symbol] = candidate

        primary_query = search_queries[0]
        web_search_result = self.runtime_ports.web_search(
            f'"{primary_query}" stock ticker symbol official'
        )
        web_candidates: list[TickerCandidate] = []
        if web_search_result.content:
            web_candidates = extract_candidates_from_search_service(
                primary_query,
                web_search_result.content,
                search_extraction_model_type=SearchExtraction,
                to_ticker_candidate_fn=to_ticker_candidate,
                llm_provider_fn=self.runtime_ports.llm_provider,
            )
        for candidate in web_candidates:
            existing = candidate_map.get(candidate.symbol)
            if existing is None or candidate.confidence > existing.confidence:
                candidate_map[candidate.symbol] = candidate

        return _SearchCandidatesOutcome(
            candidates=deduplicate_candidates(list(candidate_map.values())),
            is_degraded=web_search_result.failure_code is not None,
            degrade_error_code=web_search_result.failure_code,
            degrade_reason=web_search_result.failure_reason,
            fallback_mode=web_search_result.fallback_mode,
        )

    def parse_candidates(self, raw_candidates: object) -> list[TickerCandidate]:
        return parse_ticker_candidates(raw_candidates)

    def serialize_candidates(
        self, candidates: list[TickerCandidate]
    ) -> list[JSONObject]:
        return serialize_ticker_candidates(candidates)

    def needs_clarification(self, candidates: list[TickerCandidate]) -> bool:
        return should_request_clarification(candidates)

    def resolve_profile(self, ticker: str) -> IntentCompanyProfileLookup:
        return self.runtime_ports.company_profile(ticker)

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
        return build_artifact_payload(
            kind=OUTPUT_KIND_INTENT_EXTRACTION,
            summary=f"已確認分析標的: {resolved_ticker}",
            preview=summarize_intent_for_preview(intent_ctx),
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

        profile_lookup = self.resolve_profile(selected_symbol)
        profile = profile_lookup.profile
        if profile is None:
            log_event(
                logger,
                event="intent_clarification_profile_lookup_failed",
                message="intent clarification could not resolve company profile",
                level=logging.WARNING,
                error_code=profile_lookup.failure_code or "INTENT_PROFILE_MISSING",
                fields={
                    "selected_symbol": selected_symbol,
                    "failure_reason": profile_lookup.failure_reason,
                },
            )
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
        query_length = len(user_query.strip()) if isinstance(user_query, str) else 0
        log_event(
            logger,
            event="intent_extraction_started",
            message="intent extraction started",
            fields={
                "query_present": bool(query_length),
                "query_length": query_length,
            },
        )
        if not isinstance(user_query, str) or not user_query.strip():
            log_event(
                logger,
                event="intent_extraction_missing_query",
                message="intent extraction missing query; switching to clarification",
                level=logging.WARNING,
                error_code="INTENT_QUERY_MISSING",
            )
            log_event(
                logger,
                event="intent_extraction_completed",
                message="intent extraction completed",
                level=logging.WARNING,
                error_code="INTENT_QUERY_MISSING",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "has_intent": False,
                },
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
            intent = self.extract_intent(user_query)
            log_event(
                logger,
                event="intent_extraction_completed",
                message="intent extraction completed",
                fields={
                    "status": "searching",
                    "goto_node": "searching",
                    "is_degraded": False,
                    "has_intent": True,
                    "resolved_ticker": (
                        intent.ticker.strip()
                        if isinstance(intent.ticker, str) and intent.ticker.strip()
                        else None
                    ),
                },
            )
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
            log_event(
                logger,
                event="intent_extraction_failed",
                message="intent extraction failed",
                level=logging.ERROR,
                error_code="INTENT_EXTRACTION_FAILED",
                fields={"exception": bounded_text(exc)},
            )
            log_event(
                logger,
                event="intent_extraction_completed",
                message="intent extraction completed",
                level=logging.WARNING,
                error_code="INTENT_EXTRACTION_FAILED",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "has_intent": False,
                },
            )
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
                            "error": (
                                "Model failed to extract intent: "
                                f"{bounded_text(exc)}"
                            ),
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
        log_event(
            logger,
            event="intent_search_started",
            message="intent ticker search started",
            fields={
                "search_query_count": len(search_queries),
                "search_queries": search_queries,
            },
        )
        if not search_queries:
            log_event(
                logger,
                event="intent_search_query_missing",
                message="intent search query missing; switching to clarification",
                level=logging.WARNING,
                error_code="INTENT_SEARCH_QUERY_MISSING",
            )
            log_event(
                logger,
                event="intent_search_completed",
                message="intent ticker search completed",
                level=logging.WARNING,
                error_code="INTENT_SEARCH_QUERY_MISSING",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "candidate_count": 0,
                    "candidate_symbols": [],
                },
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
            search_raw = self.search_candidates(search_queries)
            search_outcome = (
                search_raw
                if isinstance(search_raw, _SearchCandidatesOutcome)
                else _SearchCandidatesOutcome(
                    candidates=search_raw if isinstance(search_raw, list) else [],
                    is_degraded=False,
                )
            )
            final_candidates = search_outcome.candidates
            candidate_symbols = [candidate.symbol for candidate in final_candidates]
            if search_outcome.is_degraded:
                log_event(
                    logger,
                    event="intent_search_degraded_web_channel",
                    message="intent search web channel degraded; using yahoo-first fallback",
                    level=logging.WARNING,
                    error_code=search_outcome.degrade_error_code
                    or "INTENT_SEARCH_WEB_DEGRADED",
                    fields={
                        "degrade_source": "web_search",
                        "fallback_mode": search_outcome.fallback_mode,
                        "degraded_reason": search_outcome.degrade_reason,
                        "candidate_count": len(final_candidates),
                        "search_query_count": len(search_queries),
                    },
                )
            log_event(
                logger,
                event="intent_search_completed",
                message="intent ticker search completed",
                fields={
                    "status": "deciding",
                    "goto_node": "deciding",
                    "is_degraded": search_outcome.is_degraded,
                    "candidate_count": len(final_candidates),
                    "candidate_symbols": candidate_symbols,
                },
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
                    "candidate_symbols": candidate_symbols,
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
                detail={"exception": bounded_text(exc)},
                level=logging.ERROR,
            )
            log_event(
                logger,
                event="intent_search_failed",
                message="intent ticker search failed",
                level=logging.ERROR,
                error_code="INTENT_SEARCH_FAILED",
                fields={"exception": bounded_text(exc)},
            )
            log_event(
                logger,
                event="intent_search_completed",
                message="intent ticker search completed",
                level=logging.WARNING,
                error_code="INTENT_SEARCH_FAILED",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "candidate_count": 0,
                    "candidate_symbols": [],
                },
            )
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
                                f"{bounded_text(exc)}. Switching to manual selection."
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
        candidate_count = len(candidates) if isinstance(candidates, list) else 0
        log_event(
            logger,
            event="intent_decision_started",
            message="intent decision started",
            fields={"candidate_count": candidate_count},
        )
        if not isinstance(candidates, list) or not candidates:
            log_event(
                logger,
                event="intent_decision_no_candidates",
                message="intent decision found no candidates; switching to clarification",
                level=logging.WARNING,
                error_code="INTENT_CANDIDATES_MISSING",
            )
            log_event(
                logger,
                event="intent_decision_completed",
                message="intent decision completed",
                level=logging.WARNING,
                error_code="INTENT_CANDIDATES_MISSING",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "resolved_ticker": None,
                    "candidate_count": 0,
                },
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
                log_event(
                    logger,
                    event="intent_decision_ambiguous",
                    message="intent decision detected ambiguity; requesting clarification",
                    level=logging.WARNING,
                    error_code="INTENT_TICKER_AMBIGUOUS",
                    fields={"candidate_count": len(candidate_objs)},
                )
                log_event(
                    logger,
                    event="intent_decision_completed",
                    message="intent decision completed",
                    level=logging.WARNING,
                    error_code="INTENT_TICKER_AMBIGUOUS",
                    fields={
                        "status": "clarifying",
                        "goto_node": "clarifying",
                        "is_degraded": True,
                        "resolved_ticker": None,
                        "candidate_count": len(candidate_objs),
                    },
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
            log_event(
                logger,
                event="intent_decision_resolved",
                message="intent decision resolved ticker",
                fields={"resolved_ticker": resolved_ticker},
            )
            profile_lookup = self.resolve_profile(resolved_ticker)
            profile = profile_lookup.profile
            if profile is None:
                log_event(
                    logger,
                    event="intent_decision_profile_missing",
                    message="intent decision could not resolve company profile",
                    level=logging.WARNING,
                    error_code=profile_lookup.failure_code or "INTENT_PROFILE_MISSING",
                    fields={
                        "resolved_ticker": resolved_ticker,
                        "failure_reason": profile_lookup.failure_reason,
                    },
                )
                log_event(
                    logger,
                    event="intent_decision_completed",
                    message="intent decision completed",
                    level=logging.WARNING,
                    error_code=profile_lookup.failure_code or "INTENT_PROFILE_MISSING",
                    fields={
                        "status": "clarifying",
                        "goto_node": "clarifying",
                        "is_degraded": True,
                        "resolved_ticker": resolved_ticker,
                        "candidate_count": len(candidate_objs),
                    },
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
            log_event(
                logger,
                event="intent_decision_completed",
                message="intent decision completed",
                fields={
                    "status": "resolved",
                    "goto_node": "END",
                    "is_degraded": False,
                    "resolved_ticker": resolved_ticker,
                    "candidate_count": len(candidate_objs),
                },
            )

            return IntentNodeResult(
                update={
                    "intent_extraction": resolved_ctx,
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
                detail={"exception": bounded_text(exc)},
                level=logging.ERROR,
            )
            log_event(
                logger,
                event="intent_decision_failed",
                message="intent decision failed",
                level=logging.ERROR,
                error_code="INTENT_DECISION_FAILED",
                fields={"exception": bounded_text(exc)},
            )
            log_event(
                logger,
                event="intent_decision_completed",
                message="intent decision completed",
                level=logging.WARNING,
                error_code="INTENT_DECISION_FAILED",
                fields={
                    "status": "clarifying",
                    "goto_node": "clarifying",
                    "is_degraded": True,
                    "resolved_ticker": None,
                    "candidate_count": candidate_count,
                },
            )
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
                                f"{bounded_text(exc)}. Switching to manual selection."
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
        payload = serialize_ticker_selection_interrupt_payload(
            candidates=candidate_objs,
            extracted_intent=intent_ctx.get("extracted_intent"),
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


IntentNodeResult = WorkflowNodeResult
