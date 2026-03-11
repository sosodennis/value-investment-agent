from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.core_valuation.domain.valuation_model_type_service import (
    resolve_calculator_model_type,
)
from src.agents.fundamental.model_selection.domain.entities import (
    FundamentalSelectionReport,
)
from src.agents.fundamental.model_selection.interface.report_projection_service import (
    project_selection_reports,
)
from src.agents.fundamental.workflow_orchestrator.application.state_readers import (
    read_fundamental_state,
    read_intent_state,
)
from src.agents.fundamental.workflow_orchestrator.application.state_updates import (
    build_model_selection_success_update,
    build_model_selection_waiting_update,
    build_node_error_update,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult


class ModelSelectionRuntime(Protocol):
    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None: ...

    def enrich_reasoning_with_health_context(
        self,
        reasoning: str,
        financial_reports: list[FundamentalSelectionReport],
    ) -> str: ...

    async def build_and_store_model_selection_artifact(
        self,
        *,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        model_type: str,
        reasoning: str,
        financial_reports: list[JSONObject],
        forward_signals: list[JSONObject] | None,
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]: ...


async def run_model_selection_flow(
    runtime: ModelSelectionRuntime,
    state: Mapping[str, object],
    *,
    select_valuation_model_fn: Callable[
        [CompanyProfile, list[FundamentalSelectionReport]], object
    ],
) -> FundamentalNodeResult:
    try:
        intent_state = read_intent_state(state)
        profile = intent_state.profile
        resolved_ticker = intent_state.resolved_ticker
        log_event(
            logger,
            event="fundamental_model_selection_started",
            message="fundamental model selection started",
            fields={"ticker": resolved_ticker},
        )

        if profile is None:
            log_event(
                logger,
                event="fundamental_model_selection_profile_missing",
                message="fundamental model selection missing company profile",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_PROFILE_MISSING",
                fields={"ticker": resolved_ticker},
            )
            log_event(
                logger,
                event="fundamental_model_selection_completed",
                message="fundamental model selection completed",
                level=logging.WARNING,
                fields={
                    "ticker": resolved_ticker,
                    "status": "waiting",
                    "is_degraded": True,
                    "error_code": "FUNDAMENTAL_PROFILE_MISSING",
                    "reports_count": 0,
                    "forward_signal_count": 0,
                },
            )
            return FundamentalNodeResult(
                update=build_model_selection_waiting_update(),
                goto="END",
            )

        fundamental_state = read_fundamental_state(state)
        reports_artifact_id = fundamental_state.financial_reports_artifact_id
        financial_reports: list[JSONObject] = []
        forward_signals: list[JSONObject] | None = None
        selection_reports: list[FundamentalSelectionReport] = []
        if reports_artifact_id is not None:
            bundle = await runtime.load_financial_reports_bundle(reports_artifact_id)
            if bundle is None:
                log_event(
                    logger,
                    event="fundamental_model_selection_reports_artifact_not_found",
                    message="fundamental model selection failed due to missing reports artifact payload",
                    level=logging.ERROR,
                    error_code="FUNDAMENTAL_REPORTS_ARTIFACT_NOT_FOUND",
                    fields={
                        "ticker": resolved_ticker,
                        "reports_artifact_id": reports_artifact_id,
                    },
                )
                log_event(
                    logger,
                    event="fundamental_model_selection_completed",
                    message="fundamental model selection completed",
                    level=logging.ERROR,
                    fields={
                        "ticker": resolved_ticker,
                        "status": "error",
                        "is_degraded": True,
                        "error_code": "FUNDAMENTAL_REPORTS_ARTIFACT_NOT_FOUND",
                        "reports_artifact_id": reports_artifact_id,
                        "reports_count": 0,
                        "forward_signal_count": 0,
                    },
                )
                return FundamentalNodeResult(
                    update=build_node_error_update(
                        node="model_selection",
                        error=(
                            "Financial reports artifact not found: "
                            f"{reports_artifact_id}"
                        ),
                    ),
                    goto="END",
                )
            loaded_reports, loaded_forward_signals = bundle
            selection_reports = project_selection_reports(loaded_reports)
            financial_reports = loaded_reports
            forward_signals = loaded_forward_signals

        selection = select_valuation_model_fn(profile, selection_reports)
        model = selection.model
        reasoning = selection.reasoning

        if financial_reports:
            reasoning = runtime.enrich_reasoning_with_health_context(
                reasoning,
                selection_reports,
            )

        model_type = resolve_calculator_model_type(model.value)

        artifact: AgentOutputArtifactPayload | None
        report_id: str | None
        try:
            (
                artifact,
                report_id,
            ) = await runtime.build_and_store_model_selection_artifact(
                intent_ctx=intent_state.context,
                resolved_ticker=resolved_ticker,
                model_type=model_type,
                reasoning=reasoning,
                financial_reports=financial_reports,
                forward_signals=forward_signals,
            )
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_model_selection_artifact_failed",
                message="fundamental model selection artifact generation failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_MODEL_ARTIFACT_FAILED",
                fields={
                    "exception": str(exc),
                    "ticker": resolved_ticker,
                    "degrade_source": "model_selection_artifact",
                    "fallback_mode": "continue_without_artifact",
                    "input_count": len(financial_reports),
                    "output_count": 0,
                },
            )
            artifact, report_id = None, None

        resolved_reports_artifact_id = report_id or reports_artifact_id
        if resolved_reports_artifact_id is None:
            log_event(
                logger,
                event="fundamental_model_selection_report_id_missing",
                message="fundamental model selection missing reports artifact id for valuation handoff",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_MODEL_SELECTION_REPORT_ID_MISSING",
                fields={
                    "ticker": resolved_ticker,
                    "model_type": model_type,
                    "reports_count": len(financial_reports),
                    "forward_signal_count": len(forward_signals or []),
                },
            )
            log_event(
                logger,
                event="fundamental_model_selection_completed",
                message="fundamental model selection completed",
                level=logging.ERROR,
                fields={
                    "ticker": resolved_ticker,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "FUNDAMENTAL_MODEL_SELECTION_REPORT_ID_MISSING",
                    "reports_count": len(financial_reports),
                    "forward_signal_count": len(forward_signals or []),
                },
            )
            return FundamentalNodeResult(
                update=build_node_error_update(
                    node="model_selection",
                    error="Missing financial reports artifact id for valuation handoff",
                ),
                goto="END",
            )

        fa_update: JSONObject = {
            "model_type": model_type,
            "financial_reports_artifact_id": resolved_reports_artifact_id,
        }
        prior_quality_gates = fundamental_state.context.get("xbrl_quality_gates")
        if isinstance(prior_quality_gates, Mapping):
            fa_update["xbrl_quality_gates"] = dict(prior_quality_gates)
        prior_diagnostics = fundamental_state.context.get("xbrl_diagnostics")
        if isinstance(prior_diagnostics, Mapping):
            fa_update["xbrl_diagnostics"] = dict(prior_diagnostics)
        if artifact is not None:
            fa_update["artifact"] = artifact

        reports_count = len(financial_reports)
        forward_signal_count = len(forward_signals or [])
        is_degraded = artifact is None
        log_event(
            logger,
            event="fundamental_model_selection_completed",
            message="fundamental model selection completed",
            level=logging.WARNING if is_degraded else logging.INFO,
            fields={
                "ticker": resolved_ticker,
                "status": "done",
                "is_degraded": is_degraded,
                "model_type": model_type,
                "reports_count": reports_count,
                "forward_signal_count": forward_signal_count,
                "artifact_written": artifact is not None,
            },
        )
        return FundamentalNodeResult(
            update=build_model_selection_success_update(
                fa_update=fa_update,
            ),
            goto="calculation",
        )
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_model_selection_failed",
            message="fundamental model selection failed",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_MODEL_SELECTION_FAILED",
            fields={"exception": str(exc)},
        )
        log_event(
            logger,
            event="fundamental_model_selection_completed",
            message="fundamental model selection completed",
            level=logging.ERROR,
            fields={
                "status": "error",
                "is_degraded": True,
                "error_code": "FUNDAMENTAL_MODEL_SELECTION_FAILED",
                "reports_count": 0,
                "forward_signal_count": 0,
            },
        )
        return FundamentalNodeResult(
            update=build_node_error_update(
                node="model_selection",
                error=str(exc),
            ),
            goto="END",
        )
