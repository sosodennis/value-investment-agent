from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_alerts_compute_error_update,
    build_alerts_compute_success_update,
)
from src.agents.technical.interface.serializers import build_alerts_compute_preview
from src.agents.technical.subdomains.alerts import (
    AlertRuntimeRequest,
    AlertRuntimeResult,
    AlertRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class AlertsComputeRuntime(Protocol):
    async def load_indicator_series(
        self, artifact_id: str
    ) -> TechnicalIndicatorSeriesArtifactData | None: ...

    async def load_pattern_pack(
        self, artifact_id: str
    ) -> TechnicalPatternPackArtifactData | None: ...

    async def save_alerts(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_alerts_compute_use_case(
    runtime: AlertsComputeRuntime,
    state: Mapping[str, object],
    *,
    alert_runtime: AlertRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_alerts_compute_started",
        message="technical alerts computation started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    indicator_series_id = technical_context.indicator_series_id
    pattern_pack_id = technical_context.pattern_pack_id

    indicator_series = None
    pattern_pack = None
    degraded_reasons: list[str] = []
    input_count = 0

    if indicator_series_id:
        indicator_series = await runtime.load_indicator_series(indicator_series_id)
        if indicator_series is None:
            degraded_reasons.append("INDICATOR_SERIES_NOT_FOUND")
        else:
            input_count += 1
    else:
        degraded_reasons.append("INDICATOR_SERIES_ID_MISSING")

    if pattern_pack_id:
        pattern_pack = await runtime.load_pattern_pack(pattern_pack_id)
        if pattern_pack is None:
            degraded_reasons.append("PATTERN_PACK_NOT_FOUND")
        else:
            input_count += 1
    else:
        degraded_reasons.append("PATTERN_PACK_ID_MISSING")

    as_of = (
        indicator_series.as_of
        if indicator_series is not None
        else pattern_pack.as_of
        if pattern_pack is not None
        else datetime.now().isoformat()
    )

    try:
        alert_request = AlertRuntimeRequest(
            ticker=ticker_value or "N/A",
            as_of=as_of,
            indicator_series=indicator_series,
            pattern_pack=pattern_pack,
        )
        alert_result = alert_runtime.compute(alert_request)
    except Exception as exc:
        log_event(
            logger,
            event="technical_alerts_compute_failed",
            message="technical alerts computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_ALERTS_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_alerts_compute_completed",
            message="technical alerts computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_ALERTS_COMPUTE_FAILED",
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_alerts_compute_error_update(
                f"Computation crashed: {str(exc)}"
            ),
            goto="END",
        )

    combined_degraded = list({*degraded_reasons, *alert_result.degraded_reasons})
    if combined_degraded:
        log_event(
            logger,
            event="technical_alerts_compute_degraded",
            message="technical alerts computation completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_ALERTS_COMPUTE_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "alert_runtime",
                "fallback_mode": "continue_with_partial_alerts",
                "degraded_reasons": combined_degraded,
                "input_count": input_count,
                "output_count": len(alert_result.alerts),
            },
        )
    payload = _alerts_to_payload(
        alert_result,
        combined_degraded,
        {
            "indicator_series_id": indicator_series_id,
            "pattern_pack_id": pattern_pack_id,
        },
    )
    alerts_id = await runtime.save_alerts(
        data=payload,
        produced_by="technical_analysis.alerts_compute",
        key_prefix=ticker_value,
    )

    summary = payload.get("summary")
    summary_dict = summary if isinstance(summary, dict) else {}
    preview = build_alerts_compute_preview(
        ticker=ticker_value or "N/A",
        alert_count=summary_dict.get("total", 0),
        critical_count=summary_dict.get("severity_counts", {}).get("critical", 0),
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Alerts computed for {ticker_value or 'N/A'}",
        preview,
    )

    log_event(
        logger,
        event="technical_alerts_compute_completed",
        message="technical alerts computation completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(combined_degraded),
            "alerts_id": alerts_id,
            "alert_count": len(alert_result.alerts),
            "input_count": input_count,
            "output_count": len(alert_result.alerts),
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_alerts_compute_success_update(
            alerts_id=alerts_id,
            artifact=artifact,
        ),
        goto="regime_compute",
    )


def _alerts_to_payload(
    result: AlertRuntimeResult,
    degraded_reasons: list[str],
    source_artifacts: dict[str, str | None],
) -> JSONObject:
    alerts = []
    for alert in result.alerts:
        policy = None
        if alert.policy is not None:
            policy = {
                "policy_code": alert.policy.policy_code,
                "policy_version": alert.policy.policy_version,
                "lifecycle_state": alert.policy.lifecycle_state,
                "evidence_refs": [
                    {
                        "artifact_kind": ref.artifact_kind,
                        "artifact_id": ref.artifact_id,
                        "timeframe": ref.timeframe,
                        "signal_key": ref.signal_key,
                    }
                    for ref in alert.policy.evidence_refs
                ]
                or None,
                "quality_gate": alert.policy.quality_gate,
                "trigger_reason": alert.policy.trigger_reason,
                "suppression_reason": alert.policy.suppression_reason,
            }
        alerts.append(
            {
                "code": alert.code,
                "severity": alert.severity,
                "timeframe": alert.timeframe,
                "title": alert.title,
                "message": alert.message,
                "value": alert.value,
                "threshold": alert.threshold,
                "direction": alert.direction,
                "triggered_at": alert.triggered_at,
                "source": alert.source,
                "metadata": alert.metadata,
                "policy": policy,
            }
        )

    return {
        "ticker": result.ticker,
        "as_of": result.as_of,
        "alerts": alerts,
        "summary": {
            "total": result.summary.total,
            "severity_counts": result.summary.severity_counts,
            "generated_at": result.summary.generated_at,
            "policy_count": result.summary.policy_count,
            "lifecycle_counts": result.summary.lifecycle_counts,
            "quality_gate_counts": result.summary.quality_gate_counts,
        },
        "degraded_reasons": degraded_reasons or None,
        "source_artifacts": source_artifacts or None,
    }
