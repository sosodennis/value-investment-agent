from __future__ import annotations

from src.agents.fundamental.application.workflow_orchestrator.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.application.workflow_orchestrator.ports import (
    FundamentalFinancialStatementsPayload,
)
from src.agents.fundamental.subdomains.artifacts_provenance.infrastructure.fundamental_artifact_repository import (
    fundamental_artifact_repository,
)
from src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl import (
    fetch_financial_reports_payload,
)
from src.agents.fundamental.subdomains.forward_signals.application.extraction_service import (
    extract_forward_signals,
)
from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl import (
    build_finbert_direction_reviewer,
    extract_forward_signals_from_sec_text,
    extract_forward_signals_from_xbrl_reports,
)
from src.agents.fundamental.subdomains.market_data.infrastructure.factory import (
    market_data_service,
)
from src.agents.news.infrastructure.sentiment.finbert_sentiment_provider import (
    get_finbert_analyzer,
)


def _normalize_financial_reports_contract(
    payload: dict[str, object],
) -> FundamentalFinancialStatementsPayload:
    reports_raw = payload.get("financial_reports")
    financial_reports = reports_raw if isinstance(reports_raw, list) else []

    diagnostics_raw = payload.get("diagnostics")
    diagnostics = dict(diagnostics_raw) if isinstance(diagnostics_raw, dict) else None

    quality_gates_raw = payload.get("quality_gates")
    quality_gates = (
        dict(quality_gates_raw) if isinstance(quality_gates_raw, dict) else None
    )

    return {
        "financial_reports": financial_reports,
        "diagnostics": diagnostics,
        "quality_gates": quality_gates,
    }


_finbert_direction_reviewer = build_finbert_direction_reviewer(get_finbert_analyzer)


def _extract_forward_signals_text(
    *, ticker: str, rules_sector: str | None = None
) -> list[dict[str, object]]:
    return extract_forward_signals_from_sec_text(
        ticker=ticker,
        rules_sector=rules_sector,
        review_signal_direction_with_finbert_fn=_finbert_direction_reviewer,
    )


def _extract_forward_signals(ticker: str, reports_raw: list[dict[str, object]]):
    return extract_forward_signals(
        ticker=ticker,
        reports_raw=reports_raw,
        extract_xbrl_fn=extract_forward_signals_from_xbrl_reports,
        extract_text_fn=_extract_forward_signals_text,
    )


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    orchestrator = build_fundamental_orchestrator(port=fundamental_artifact_repository)
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fetch_financial_reports_fn=(
            lambda ticker, *, years=5: _normalize_financial_reports_contract(
                fetch_financial_reports_payload(ticker=ticker, years=years)
            )
        ),
        extract_forward_signals_fn=_extract_forward_signals,
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
