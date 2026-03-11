from __future__ import annotations

from src.agents.fundamental.application.workflow_orchestrator.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.application.workflow_orchestrator.ports import (
    FundamentalFinancialPayload,
)
from src.agents.fundamental.subdomains.artifacts_provenance.infrastructure.fundamental_artifact_repository import (
    fundamental_artifact_repository,
)
from src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl import (
    fetch_financial_payload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.parsers import (
    parse_forward_signals,
)
from src.agents.fundamental.subdomains.market_data.infrastructure.factory import (
    market_data_service,
)


def _normalize_financial_payload_contract(
    payload: dict[str, object],
) -> FundamentalFinancialPayload:
    reports_raw = payload.get("financial_reports")
    financial_reports = reports_raw if isinstance(reports_raw, list) else []

    forward_signals = parse_forward_signals(
        payload.get("forward_signals"),
        context="fundamental.financial_payload.forward_signals",
    )

    diagnostics_raw = payload.get("diagnostics")
    diagnostics = dict(diagnostics_raw) if isinstance(diagnostics_raw, dict) else None

    quality_gates_raw = payload.get("quality_gates")
    quality_gates = (
        dict(quality_gates_raw) if isinstance(quality_gates_raw, dict) else None
    )

    return {
        "financial_reports": financial_reports,
        "forward_signals": forward_signals,
        "diagnostics": diagnostics,
        "quality_gates": quality_gates,
    }


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    orchestrator = build_fundamental_orchestrator(port=fundamental_artifact_repository)
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fetch_financial_payload_fn=(
            lambda ticker, *, years=5: _normalize_financial_payload_contract(
                fetch_financial_payload(ticker=ticker, years=years)
            )
        ),
        market_data_service=market_data_service,
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
