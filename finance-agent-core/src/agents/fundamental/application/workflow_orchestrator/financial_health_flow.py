from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.context_mapper_service import (
    build_fundamental_app_context,
)
from src.agents.fundamental.application.workflow_orchestrator.dto import (
    FundamentalAppContextDTO,
)
from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_intent_state,
)
from src.agents.fundamental.application.workflow_orchestrator.state_updates import (
    build_financial_health_missing_ticker_update,
    build_financial_health_success_update,
    build_node_error_update,
)
from src.agents.fundamental.subdomains.financial_statements.interface.parsers import (
    FinancialStatementsPayload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.serializers import (
    serialize_forward_signals,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult


class FinancialHealthRuntime(Protocol):
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject] | None], JSONObject
    ]
    build_progress_artifact: Callable[[str, JSONObject], AgentOutputArtifactPayload]

    async def save_financial_reports(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


async def run_financial_health_flow(
    runtime: FinancialHealthRuntime,
    state: Mapping[str, object],
    *,
    fetch_financial_reports_fn: Callable[[str], FinancialStatementsPayload],
    extract_forward_signals_fn: Callable[
        [str, list[JSONObject]], list[ForwardSignalPayload] | None
    ],
) -> FundamentalNodeResult:
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
    try:
        payload = await asyncio.to_thread(
            fetch_financial_reports_fn,
            resolved_ticker,
        )
        reports_data = payload.financial_reports
        diagnostics = payload.diagnostics
        quality_gates = payload.quality_gates
        forward_signals = await asyncio.to_thread(
            extract_forward_signals_fn,
            resolved_ticker,
            reports_data,
        )
        reports_artifact_id: str | None = None
        artifact: AgentOutputArtifactPayload | None = None

        if reports_data:
            artifact_payload: JSONObject = {"financial_reports": reports_data}
            if forward_signals:
                serialized_signals = serialize_forward_signals(forward_signals)
                if serialized_signals is not None:
                    artifact_payload["forward_signals"] = serialized_signals
            if isinstance(diagnostics, dict):
                artifact_payload["diagnostics"] = diagnostics
            if isinstance(quality_gates, dict):
                artifact_payload["quality_gates"] = quality_gates
            reports_artifact_id = await runtime.save_financial_reports(
                data=artifact_payload,
                produced_by="fundamental_analysis.financial_health",
                key_prefix=f"fa_reports_{resolved_ticker}",
            )
            mapper_ctx = build_fundamental_app_context(
                intent_state.context,
                resolved_ticker,
                status="fetching_complete",
            )
            preview = runtime.summarize_preview(mapper_ctx, reports_data)
            artifact = runtime.build_progress_artifact(
                f"Fundamental Analysis: Data fetched for {resolved_ticker}",
                preview,
            )
        else:
            log_event(
                logger,
                event="fundamental_financial_health_empty_reports",
                message="financial health reports unavailable; continuing without reports",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_REPORTS_UNAVAILABLE",
                fields={
                    "ticker": resolved_ticker,
                    "degrade_source": "xbrl_reports",
                    "fallback_mode": "continue_without_reports",
                    "input_count": 0,
                    "output_count": 0,
                },
            )

        forward_signal_count = len(forward_signals or [])
        reports_count = len(reports_data)
        is_degraded = reports_count == 0
        log_event(
            logger,
            event="fundamental_financial_health_completed",
            message="fundamental financial health completed",
            level=logging.WARNING if is_degraded else logging.INFO,
            fields={
                "ticker": resolved_ticker,
                "status": "done",
                "is_degraded": is_degraded,
                "reports_count": reports_count,
                "forward_signal_count": forward_signal_count,
                "artifact_written": reports_artifact_id is not None,
                "xbrl_quality_status": (
                    quality_gates.get("status")
                    if isinstance(quality_gates, Mapping)
                    else None
                ),
                "xbrl_quality_blocking_count": (
                    quality_gates.get("blocking_count")
                    if isinstance(quality_gates, Mapping)
                    else None
                ),
            },
        )
        return FundamentalNodeResult(
            update=build_financial_health_success_update(
                reports_artifact_id=reports_artifact_id,
                artifact=artifact,
                diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
                quality_gates=quality_gates
                if isinstance(quality_gates, dict)
                else None,
            ),
            goto="model_selection",
        )
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_financial_health_failed",
            message="fundamental financial health failed",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_FINANCIAL_HEALTH_FAILED",
            fields={"exception": str(exc), "ticker": resolved_ticker},
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
                "error_code": "FUNDAMENTAL_FINANCIAL_HEALTH_FAILED",
                "reports_count": 0,
                "forward_signal_count": 0,
            },
        )
        return FundamentalNodeResult(
            update=build_node_error_update(
                node="financial_health",
                error=str(exc),
            ),
            goto="END",
        )
