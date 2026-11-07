from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_intent_state,
)
from src.agents.fundamental.application.workflow_orchestrator.state_updates import (
    build_financial_health_missing_ticker_update,
    build_financial_health_success_update,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult


class FinancialHealthRuntime(Protocol):
    """Compatibility seam for the orchestrator-owned workflow runner."""

    pass


async def run_financial_health_flow(
    runtime: FinancialHealthRuntime,
    state: Mapping[str, object],
) -> FundamentalNodeResult:
    del runtime
    intent_state = read_intent_state(state)
    resolved_ticker = intent_state.resolved_ticker
    log_event(
        logger,
        event="fundamental_financial_health_started",
        message="fundamental financial health started",
        fields={"ticker": resolved_ticker},
    )
    if resolved_ticker is None:
        log_event(
            logger,
            event="fundamental_financial_health_missing_ticker",
            message="fundamental financial health missing resolved ticker",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_TICKER_MISSING",
        )
        log_event(
            logger,
            event="fundamental_financial_health_completed",
            message="fundamental financial health completed",
            level=logging.ERROR,
            fields={
                "ticker": resolved_ticker,
                "status": "error",
                "is_degraded": True,
                "error_code": "FUNDAMENTAL_TICKER_MISSING",
                "reports_count": 0,
                "forward_signal_count": 0,
            },
        )
        return FundamentalNodeResult(
            update=build_financial_health_missing_ticker_update(),
            goto="END",
        )
    diagnostics = {
        "status": "unavailable",
        "reason": "service_snapshot_request_required",
        "ticker": resolved_ticker,
    }
    quality_gates = {
        "status": "unavailable",
        "source": "fundamental_service",
        "blocking_count": 0,
    }
    log_event(
        logger,
        event="fundamental_financial_health_empty_reports",
        message="financial health reports unavailable; waiting for service snapshot",
        level=logging.WARNING,
        error_code="FUNDAMENTAL_SERVICE_FACTS_UNAVAILABLE",
        fields={
            "ticker": resolved_ticker,
            "degrade_source": "fundamental_service",
            "fallback_mode": "service_snapshot_pending",
            "input_count": 0,
            "output_count": 0,
        },
    )
    log_event(
        logger,
        event="fundamental_financial_health_completed",
        message="fundamental financial health completed",
        level=logging.WARNING,
        fields={
            "ticker": resolved_ticker,
            "status": "done",
            "is_degraded": True,
            "reports_count": 0,
            "forward_signal_count": 0,
            "artifact_written": False,
            "xbrl_quality_status": quality_gates["status"],
            "xbrl_quality_blocking_count": quality_gates["blocking_count"],
        },
    )
    return FundamentalNodeResult(
        update=build_financial_health_success_update(
            artifact=None,
            diagnostics=diagnostics,
            quality_gates=quality_gates,
        ),
        goto="model_selection",
    )
