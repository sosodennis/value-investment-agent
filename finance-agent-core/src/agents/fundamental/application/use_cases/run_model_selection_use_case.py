from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.report_projection_service import (
    project_selection_reports,
)
from src.agents.fundamental.application.state_readers import (
    read_fundamental_state,
    read_intent_state,
)
from src.agents.fundamental.application.state_updates import (
    build_model_selection_success_update,
    build_model_selection_waiting_update,
    build_node_error_update,
)
from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.valuation_model_type_service import (
    resolve_calculator_model_type,
)
from src.agents.fundamental.interface.serializers import (
    serialize_model_selection_details,
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


async def run_model_selection_use_case(
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

        if profile is None:
            log_event(
                logger,
                event="fundamental_model_selection_profile_missing",
                message="fundamental model selection missing company profile",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_PROFILE_MISSING",
                fields={"ticker": resolved_ticker},
            )
            return FundamentalNodeResult(
                update=build_model_selection_waiting_update(),
                goto="clarifying",
            )

        fundamental_state = read_fundamental_state(state)
        reports_artifact_id = fundamental_state.financial_reports_artifact_id
        financial_reports: list[JSONObject] = []
        forward_signals: list[JSONObject] | None = None
        selection_reports: list[FundamentalSelectionReport] = []
        if reports_artifact_id is not None:
            bundle = await runtime.load_financial_reports_bundle(reports_artifact_id)
            if bundle is not None:
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

        selection_details = serialize_model_selection_details(selection)
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
                fields={"exception": str(exc), "ticker": resolved_ticker},
            )
            artifact, report_id = None, None

        fa_update: JSONObject = {
            "model_type": model_type,
            "selected_model": model.value,
            "valuation_summary": reasoning,
            "financial_reports_artifact_id": report_id or reports_artifact_id,
            "model_selection_details": selection_details,
        }
        if artifact is not None:
            fa_update["artifact"] = artifact

        return FundamentalNodeResult(
            update=build_model_selection_success_update(
                fa_update=fa_update,
                resolved_ticker=resolved_ticker,
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
        return FundamentalNodeResult(
            update=build_node_error_update(
                node="model_selection",
                error=str(exc),
            ),
            goto="END",
        )
