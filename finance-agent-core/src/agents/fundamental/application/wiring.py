from __future__ import annotations

from src.agents.fundamental.application.workflow_orchestrator.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.application.workflow_orchestrator.ports import (
    FundamentalFinancialStatementsPayload,
)
from src.agents.fundamental.capabilities.artifacts_provenance.public import (
    fundamental_artifact_repository,
)
from src.agents.fundamental.infrastructure import HttpFundamentalServiceClient


def _service_snapshot_pending_payload(
    ticker: str, *, years: int = 5
) -> FundamentalFinancialStatementsPayload:
    """Keep the Agent degraded until a service-owned snapshot is supplied."""

    _ = years
    return {
        "financial_reports": [],
        "diagnostics": {
            "status": "unavailable",
            "reason": "service_snapshot_request_required",
            "ticker": ticker,
        },
        "quality_gates": {
            "status": "unavailable",
            "source": "fundamental_service",
            "blocking_count": 0,
        },
    }


def _no_forward_signals(*, ticker: str, reports_raw: list[dict[str, object]]) -> None:
    """Legacy signal extraction has no input until service facts are present."""

    _ = (ticker, reports_raw)
    return None


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    orchestrator = build_fundamental_orchestrator(port=fundamental_artifact_repository)
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fetch_financial_reports_fn=_service_snapshot_pending_payload,
        extract_forward_signals_fn=_no_forward_signals,
        fundamental_service_client=HttpFundamentalServiceClient(),
    )


_fundamental_workflow_runner: FundamentalWorkflowRunner | None = None


def get_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    global _fundamental_workflow_runner
    if _fundamental_workflow_runner is None:
        _fundamental_workflow_runner = build_default_fundamental_workflow_runner()
    return _fundamental_workflow_runner


__all__ = [
    "FundamentalWorkflowRunner",
    "build_default_fundamental_workflow_runner",
    "get_fundamental_workflow_runner",
]
