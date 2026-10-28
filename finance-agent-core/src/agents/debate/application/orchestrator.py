from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from src.agents.debate.application.debate_history_service import (
    build_citation_audit_payload,
    build_verdict_history_text,
)
from src.agents.debate.application.debate_service import (
    DEBATE_LLM_TIMEOUT_SECONDS,
    MAX_CHAR_HISTORY,
    execute_bear_round,
    execute_bull_round,
    execute_moderator_round,
    extract_debate_facts,
)
from src.agents.debate.application.ports import (
    DebateArtifactRepositoryPort,
    DebateSourceReaderPort,
    SycophancyDetectorPort,
)
from src.agents.debate.application.prompt_runtime import (
    get_trimmed_history,
    hash_text,
    log_llm_config,
    log_llm_response,
    log_messages,
)
from src.agents.debate.application.report_service import prepare_debate_reports
from src.agents.debate.application.state_readers import resolved_ticker_from_state
from src.agents.debate.application.state_updates import build_debate_success_update
from src.agents.debate.domain.entities import DebateVerdictDraft, EvidenceFact
from src.agents.debate.domain.pragmatic_verdict_policy import (
    calculate_pragmatic_verdict,
)
from src.agents.debate.domain.validators import FactValidator
from src.agents.debate.interface.serializers import build_final_report_payload
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderPort,
    LLMRequestClass,
    ModelRoute,
    StructuredRequest,
)
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_ARTIFACT_JSON,
    CONTRACT_KIND_WORKFLOW_STATE,
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowFanoutNodeResult

logger = get_logger(__name__)


class _RiskFreeRateProvider(Protocol):
    def __call__(self) -> float: ...


class _DynamicPayoffMapProvider(Protocol):
    def __call__(self, ticker: str | None, risk_profile: str) -> dict[str, float]: ...


DebateNodeResult = WorkflowFanoutNodeResult


@dataclass(frozen=True)
class DebateOrchestrator:
    source_reader: DebateSourceReaderPort
    artifact_port: DebateArtifactRepositoryPort
    llm_provider: LLMProviderPort
    llm_route: ModelRoute
    get_sycophancy_detector_fn: Callable[[], SycophancyDetectorPort]
    summarize_preview_fn: Callable[[JSONObject], JSONObject]
    build_output_artifact_fn: Callable[
        [str, JSONObject, str | None], AgentOutputArtifactPayload | None
    ]
    get_risk_free_rate_fn: _RiskFreeRateProvider
    get_payoff_map_fn: _DynamicPayoffMapProvider

    async def run_debate_aggregator(
        self, state: Mapping[str, object]
    ) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        if ticker is None:
            log_boundary_event(
                logger,
                node="debate.aggregator",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_WORKFLOW_STATE,
                error_code="DEBATE_MISSING_TICKER",
                state=state,
                level=logging.ERROR,
            )
            return DebateNodeResult(
                update={
                    "workflow_activity_updates": {"debate_aggregator": "error"},
                    "error_logs": [
                        {
                            "node": "debate_aggregator",
                            "error": "Missing intent_extraction.resolved_ticker",
                            "severity": "error",
                            "error_code": "DEBATE_MISSING_TICKER",
                            "contract_kind": CONTRACT_KIND_WORKFLOW_STATE,
                            "artifact_id": None,
                            "diagnostics": build_replay_diagnostics(
                                state, node="debate.aggregator"
                            ),
                        }
                    ],
                },
                goto="END",
            )

        reports = await prepare_debate_reports(state, source_reader=self.source_reader)
        context_summary_text = self._compress_reports(reports.payload)
        is_degraded = reports.is_degraded
        degraded_reasons = reports.degraded_reason_codes
        if is_degraded:
            log_event(
                logger,
                event="debate_aggregator_sources_degraded",
                message="debate aggregator source data degraded",
                level=logging.WARNING,
                error_code="DEBATE_SOURCE_DATA_DEGRADED",
                fields={
                    "ticker": ticker,
                    "degraded_reason_count": len(degraded_reasons),
                    "degraded_reasons": degraded_reasons,
                },
            )
        log_event(
            logger,
            event="debate_aggregator_reports_prepared",
            message="debate aggregator prepared compressed reports",
            fields={
                "ticker": ticker,
                "context_summary_chars": len(context_summary_text),
                "context_summary_hash": hash_text(context_summary_text),
                "source": "computed",
                "is_degraded": is_degraded,
                "degraded_reason_count": len(degraded_reasons),
            },
        )
        log_boundary_event(
            logger,
            node="debate.aggregator",
            artifact_id=None,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="OK",
            state=state,
            detail={
                "ticker": ticker,
                "financial_reports_count": len(
                    reports.payload.get("financials", {}).get("data", [])
                )
                if isinstance(reports.payload.get("financials"), Mapping)
                else 0,
                "is_degraded": is_degraded,
                "degraded_reasons": degraded_reasons,
            },
        )

        error_logs = (
            [
                {
                    "node": "debate_aggregator",
                    "error": f"degraded source inputs: {', '.join(degraded_reasons)}",
                    "severity": "warning",
                }
            ]
            if is_degraded
            else []
        )
        return DebateNodeResult(
            update={
                "active_activity_id": "debate_aggregator",
                "workflow_activity_updates": {
                    "debate_aggregator": "done",
                    "r1_bull": "running",
                    "r1_bear": "running",
                },
                "context_summary_text": context_summary_text,
                **({"error_logs": error_logs} if error_logs else {}),
            },
            goto=["fact_extractor"],
        )

    async def run_fact_extractor(self, state: Mapping[str, object]) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        if ticker is None:
            log_boundary_event(
                logger,
                node="debate.fact_extractor",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_WORKFLOW_STATE,
                error_code="DEBATE_MISSING_TICKER",
                state=state,
                level=logging.ERROR,
            )
            return DebateNodeResult(
                update={
                    "fact_extraction_status": "error",
                    "workflow_activity_updates": {"fact_extractor": "error"},
                    "error_logs": [
                        {
                            "node": "fact_extractor",
                            "error": "Missing intent_extraction.resolved_ticker",
                            "severity": "error",
                            "error_code": "DEBATE_MISSING_TICKER",
                            "contract_kind": CONTRACT_KIND_WORKFLOW_STATE,
                            "artifact_id": None,
                            "diagnostics": build_replay_diagnostics(
                                state, node="debate.fact_extractor"
                            ),
                        }
                    ],
                },
                goto="END",
            )

        log_event(
            logger,
            event="debate_fact_extraction_started",
            message="debate fact extraction started",
            fields={"ticker": ticker},
        )
        extracted = await extract_debate_facts(state, source_reader=self.source_reader)
        artifact_id = await self.artifact_port.save_facts_bundle(
            data=extracted.bundle_payload,
            produced_by="debate.fact_extractor",
            key_prefix=extracted.ticker,
        )
        log_event(
            logger,
            event="debate_fact_extraction_completed",
            message="debate fact extraction completed",
            fields={
                "ticker": ticker,
                "facts_count": len(extracted.facts),
                "artifact_id": artifact_id,
            },
        )
        log_boundary_event(
            logger,
            node="debate.fact_extractor",
            artifact_id=artifact_id,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="OK",
            state=state,
            detail={"ticker": ticker, "facts_count": len(extracted.facts)},
        )

        return DebateNodeResult(
            update={
                "facts_artifact_id": artifact_id,
                "facts_hash": extracted.facts_hash,
                "facts_summary": extracted.summary,
                "fact_extraction_status": "done",
                "facts_registry_text": extracted.strict_facts_registry,
            },
            goto=["r1_bull", "r1_bear"],
        )

    async def run_bull_round(
        self,
        state: Mapping[str, object],
        *,
        round_num: int,
        adversarial_rule: str,
        system_prompt_template: str,
        node_name: str,
        success_goto: str,
        success_progress: dict[str, str],
        error_progress: dict[str, str],
    ) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        log_event(
            logger,
            event="debate_bull_round_started",
            message="debate bull round started",
            fields={"node": node_name, "round_num": round_num, "ticker": ticker},
        )
        try:
            result = await execute_bull_round(
                state=state,
                round_num=round_num,
                adversarial_rule=adversarial_rule,
                system_prompt_template=system_prompt_template,
                llm_provider=self.llm_provider,
                llm_route=self.llm_route,
                source_reader=self.source_reader,
            )
            log_event(
                logger,
                event="debate_bull_round_completed",
                message="debate bull round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "done",
                    "is_degraded": False,
                },
            )
            return DebateNodeResult(
                update={
                    "history": result["history"],
                    "bull_thesis": result["bull_thesis"],
                    "workflow_activity_updates": success_progress,
                },
                goto=success_goto,
            )
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_bull_round_failed",
                message="debate bull round failed",
                level=logging.ERROR,
                error_code="DEBATE_BULL_ROUND_FAILED",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "exception": exc_text,
                },
            )
            log_event(
                logger,
                event="debate_bull_round_completed",
                message="debate bull round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "degraded",
                    "is_degraded": True,
                },
            )
            error_msg = f"Bull Agent failed in Round {round_num}: {exc_text}"
            return DebateNodeResult(
                update={
                    "history": [
                        AIMessage(
                            content=f"[SYSTEM] {error_msg}",
                            name="GrowthHunter",
                            additional_kwargs={"round_num": round_num},
                        )
                    ],
                    "bull_thesis": "[ARGUMENT MISSING]",
                    "workflow_activity_updates": error_progress,
                    "error_logs": [
                        {"node": node_name, "error": exc_text, "severity": "error"}
                    ],
                },
                goto=success_goto,
            )

    async def run_bear_round(
        self,
        state: Mapping[str, object],
        *,
        round_num: int,
        adversarial_rule: str,
        system_prompt_template: str,
        node_name: str,
        success_goto: str,
        success_progress: dict[str, str],
        error_progress: dict[str, str],
    ) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        log_event(
            logger,
            event="debate_bear_round_started",
            message="debate bear round started",
            fields={"node": node_name, "round_num": round_num, "ticker": ticker},
        )
        try:
            result = await execute_bear_round(
                state=state,
                round_num=round_num,
                adversarial_rule=adversarial_rule,
                system_prompt_template=system_prompt_template,
                llm_provider=self.llm_provider,
                llm_route=self.llm_route,
                source_reader=self.source_reader,
            )
            log_event(
                logger,
                event="debate_bear_round_completed",
                message="debate bear round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "done",
                    "is_degraded": False,
                },
            )
            return DebateNodeResult(
                update={
                    "history": result["history"],
                    "bear_thesis": result["bear_thesis"],
                    "workflow_activity_updates": success_progress,
                },
                goto=success_goto,
            )
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_bear_round_failed",
                message="debate bear round failed",
                level=logging.ERROR,
                error_code="DEBATE_BEAR_ROUND_FAILED",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "exception": exc_text,
                },
            )
            log_event(
                logger,
                event="debate_bear_round_completed",
                message="debate bear round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "degraded",
                    "is_degraded": True,
                },
            )
            error_msg = f"Bear Agent failed in Round {round_num}: {exc_text}"
            return DebateNodeResult(
                update={
                    "history": [
                        AIMessage(
                            content=f"[SYSTEM] {error_msg}",
                            name="ForensicAccountant",
                            additional_kwargs={"round_num": round_num},
                        )
                    ],
                    "bear_thesis": "[ARGUMENT MISSING]",
                    "workflow_activity_updates": error_progress,
                    "error_logs": [
                        {"node": node_name, "error": exc_text, "severity": "error"}
                    ],
                },
                goto=success_goto,
            )

    async def run_moderator_round(
        self,
        state: Mapping[str, object],
        *,
        round_num: int,
        system_prompt_template: str,
        node_name: str,
        success_goto: str,
        success_progress: dict[str, str],
        error_progress: dict[str, str],
        progress_winning_thesis: str,
        progress_summary: str,
    ) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        log_event(
            logger,
            event="debate_moderator_round_started",
            message="debate moderator round started",
            fields={"node": node_name, "round_num": round_num, "ticker": ticker},
        )
        try:
            result = await execute_moderator_round(
                state=state,
                round_num=round_num,
                system_prompt_template=system_prompt_template,
                llm_provider=self.llm_provider,
                llm_route=self.llm_route,
                detector=self.get_sycophancy_detector_fn(),
                source_reader=self.source_reader,
            )
            artifact = self._build_progress_artifact(
                current_round=round_num,
                winning_thesis=progress_winning_thesis,
                summary=progress_summary,
            )
            log_event(
                logger,
                event="debate_moderator_round_completed",
                message="debate moderator round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "done",
                    "is_degraded": False,
                },
            )
            return DebateNodeResult(
                update={
                    "history": result["history"],
                    "debate": {
                        "current_round": result["current_round"],
                        "artifact": artifact,
                    },
                    "workflow_activity_updates": success_progress,
                },
                goto=success_goto,
            )
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_moderator_round_failed",
                message="debate moderator round failed",
                level=logging.ERROR,
                error_code="DEBATE_MODERATOR_ROUND_FAILED",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "exception": exc_text,
                },
            )
            log_event(
                logger,
                event="debate_moderator_round_completed",
                message="debate moderator round completed",
                fields={
                    "node": node_name,
                    "round_num": round_num,
                    "ticker": ticker,
                    "status": "degraded",
                    "is_degraded": True,
                },
            )
            error_msg = f"Moderator failed in Round {round_num}: {exc_text}"
            return DebateNodeResult(
                update={
                    "history": [
                        AIMessage(
                            content=f"[SYSTEM] {error_msg}",
                            name="Judge",
                            additional_kwargs={"round_num": round_num},
                        )
                    ],
                    "debate": {"current_round": round_num},
                    "workflow_activity_updates": error_progress,
                    "error_logs": [
                        {"node": node_name, "error": exc_text, "severity": "error"}
                    ],
                },
                goto=success_goto,
            )

    async def run_verdict(self, state: Mapping[str, object]) -> DebateNodeResult:
        ticker = resolved_ticker_from_state(state)
        if ticker is None:
            log_event(
                logger,
                event="debate_verdict_missing_ticker",
                message="debate verdict missing resolved ticker",
                level=logging.ERROR,
                error_code="DEBATE_MISSING_TICKER",
            )
            return DebateNodeResult(
                update={
                    "workflow_activity_updates": {"verdict": "error"},
                    "error_logs": [
                        {
                            "node": "verdict",
                            "error": "Missing intent_extraction.resolved_ticker",
                            "severity": "error",
                        }
                    ],
                },
                goto="END",
            )

        try:
            log_event(
                logger,
                event="debate_verdict_started",
                message="debate verdict started",
                fields={"ticker": ticker},
            )
            log_llm_config("VERDICT", 3, self.llm_route)

            history_raw = state.get("history", [])
            history = (
                [message for message in history_raw if isinstance(message, BaseMessage)]
                if isinstance(history_raw, list)
                else []
            )
            trimmed_history = get_trimmed_history(
                history,
                max_chars=int(MAX_CHAR_HISTORY * 1.5),
            )
            history_text = build_verdict_history_text(trimmed_history)
            verdict_system = self._build_verdict_prompt(
                ticker=ticker,
                history_text=history_text,
            )

            verdict_messages = [SystemMessage(content=verdict_system)]
            log_messages(verdict_messages, "VERDICT", 3)
            conclusion_request = CompletionRequest(
                messages=(ChatMessage(role=ChatRole.SYSTEM, content=verdict_system),),
                route=self.llm_route,
                request_id=f"debate-verdict-{uuid4().hex}",
                operation="debate.verdict",
                request_class=LLMRequestClass.BACKGROUND,
                timeout_seconds=DEBATE_LLM_TIMEOUT_SECONDS,
            )
            conclusion = await self.llm_provider.acomplete_structured(
                StructuredRequest[DebateVerdictDraft](
                    completion=conclusion_request,
                    response_schema=DebateVerdictDraft,
                )
            )
            conclusion_data = conclusion.model_dump(mode="json")
            if not isinstance(conclusion_data, dict):
                raise TypeError("verdict output must serialize to JSON object")
            log_llm_response(
                "VERDICT_JSON",
                3,
                json.dumps(conclusion_data, ensure_ascii=True, indent=2),
            )

            metrics = await asyncio.to_thread(
                calculate_pragmatic_verdict,
                conclusion_data,
                ticker=ticker,
                get_risk_free_rate=self.get_risk_free_rate_fn,
                get_payoff_map=self.get_payoff_map_fn,
            )
            conclusion_data.update(metrics)
            conclusion_data["debate_rounds"] = 3

            valid_facts = await self._load_valid_facts(state)
            conclusion_data["citation_audit"] = build_citation_audit_payload(
                history=history,
                valid_facts=valid_facts,
                validate_citations_fn=FactValidator.validate_citations,
            )

            full_report_data = build_final_report_payload(
                conclusion_data=conclusion_data,
                valid_facts=valid_facts,
                history=history,
            )
            report_id = await self.artifact_port.save_final_report(
                data=full_report_data,
                produced_by="debate.verdict",
                key_prefix=ticker,
            )
            log_event(
                logger,
                event="debate_verdict_completed",
                message="debate verdict completed",
                fields={"ticker": ticker, "report_id": report_id},
            )

            artifact = self._build_final_artifact(conclusion_data, report_id=report_id)
            debate_update = build_debate_success_update(
                conclusion_data=conclusion_data,
                report_id=report_id,
                artifact=artifact,
            )

            return DebateNodeResult(
                update={
                    "debate": debate_update,
                    "workflow_activity_updates": {"verdict": "done"},
                },
                goto="END",
            )
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_verdict_failed",
                message="debate verdict failed",
                level=logging.ERROR,
                error_code="DEBATE_VERDICT_FAILED",
                fields={"ticker": ticker, "exception": exc_text},
            )
            raise

    @staticmethod
    def _compress_reports(reports: JSONObject) -> str:
        from src.agents.debate.application.prompt_runtime import compress_reports

        return compress_reports(reports)

    @staticmethod
    def _build_verdict_prompt(*, ticker: str, history_text: str) -> str:
        from src.agents.debate.interface.prompt_specs import VERDICT_PROMPT

        return VERDICT_PROMPT.format(ticker=ticker, history=history_text)

    async def _load_valid_facts(
        self, state: Mapping[str, object]
    ) -> list[EvidenceFact]:
        facts_artifact_id = state.get("facts_artifact_id")
        if not isinstance(facts_artifact_id, str):
            return []
        facts_bundle = await self.artifact_port.load_facts_bundle(facts_artifact_id)
        if facts_bundle is None:
            return []
        return facts_bundle.facts

    def _build_progress_artifact(
        self,
        *,
        current_round: int,
        winning_thesis: str,
        summary: str,
    ) -> AgentOutputArtifactPayload | None:
        try:
            preview = self.summarize_preview_fn(
                {
                    "current_round": current_round,
                    "winning_thesis": winning_thesis,
                }
            )
            return self.build_output_artifact_fn(summary, preview, None)
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_progress_artifact_failed",
                message="failed to generate debate progress artifact",
                level=logging.ERROR,
                error_code="DEBATE_PROGRESS_ARTIFACT_FAILED",
                fields={"exception": exc_text},
            )
            return None

    def _build_final_artifact(
        self,
        conclusion_data: JSONObject,
        *,
        report_id: str | None,
    ) -> AgentOutputArtifactPayload | None:
        try:
            preview = self.summarize_preview_fn(conclusion_data)
            return self.build_output_artifact_fn(
                f"Debate: {preview.get('verdict_display')}",
                preview,
                report_id,
            )
        except Exception as exc:
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_output_artifact_failed",
                message="failed to generate debate output artifact",
                level=logging.ERROR,
                error_code="DEBATE_OUTPUT_ARTIFACT_FAILED",
                fields={"exception": exc_text},
            )
            return None
