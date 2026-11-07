from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_fundamental_state,
    read_intent_state,
)
from src.agents.fundamental.application.workflow_orchestrator.state_updates import (
    build_model_selection_success_update,
    build_model_selection_waiting_update,
    build_node_error_update,
)
from src.agents.fundamental.capabilities.core_valuation.public import (
    resolve_calculator_model_type,
)
from src.agents.fundamental.capabilities.model_selection.public import (
    FundamentalSelectionReport,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult


class ModelSelectionRuntime(Protocol):
    """Compatibility seam for the orchestrator-owned workflow runner."""

    pass


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
        selection_reports: list[FundamentalSelectionReport] = []

        selection = select_valuation_model_fn(profile, selection_reports)
        model = selection.model
        reasoning = selection.reasoning

        model_type = resolve_calculator_model_type(model.value)

        fa_update: JSONObject = {
            "model_type": model_type,
            "model_selection_reasoning": reasoning,
        }
        prior_quality_gates = fundamental_state.context.get("xbrl_quality_gates")
        if isinstance(prior_quality_gates, Mapping):
            fa_update["xbrl_quality_gates"] = dict(prior_quality_gates)
        prior_diagnostics = fundamental_state.context.get("xbrl_diagnostics")
        if isinstance(prior_diagnostics, Mapping):
            fa_update["xbrl_diagnostics"] = dict(prior_diagnostics)

        quality_status = (
            prior_quality_gates.get("status")
            if isinstance(prior_quality_gates, Mapping)
            else None
        )
        diagnostics_reason = (
            prior_diagnostics.get("reason")
            if isinstance(prior_diagnostics, Mapping)
            else None
        )
        service_facts_unavailable = (
            quality_status in {None, "unavailable", "error", "block"}
            or diagnostics_reason == "service_snapshot_request_required"
        )
        fa_update.update(
            {
                "model_selection_status": (
                    "degraded" if service_facts_unavailable else "ready"
                ),
                "service_facts_status": (
                    "unavailable" if service_facts_unavailable else "available"
                ),
            }
        )

        if service_facts_unavailable:
            fa_update["degraded_reason"] = "fundamental_service_facts_unavailable"

        log_event(
            logger,
            event="fundamental_model_selection_completed",
            message="fundamental model selection completed",
            level=logging.WARNING if service_facts_unavailable else logging.INFO,
            fields={
                "ticker": resolved_ticker,
                "status": "done",
                "is_degraded": service_facts_unavailable,
                "model_type": model_type,
                "reports_count": 0,
                "forward_signal_count": 0,
                "artifact_written": False,
                "service_facts_status": fa_update["service_facts_status"],
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
