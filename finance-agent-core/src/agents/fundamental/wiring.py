from __future__ import annotations

from src.agents.fundamental.application.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.infrastructure.artifacts.fundamental_artifact_repository import (
    fundamental_artifact_repository,
)
from src.agents.fundamental.infrastructure.market_data.market_data_service import (
    market_data_service,
)
from src.agents.fundamental.infrastructure.sec_xbrl.provider import (
    fetch_financial_payload,
)


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    orchestrator = build_fundamental_orchestrator(port=fundamental_artifact_repository)
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fetch_financial_payload_fn=(
            lambda ticker, *, years=3: fetch_financial_payload(
                ticker=ticker, years=years
            )
        ),
        market_data_service=market_data_service,
    )


fundamental_workflow_runner = build_default_fundamental_workflow_runner()


__all__ = [
    "FundamentalWorkflowRunner",
    "build_default_fundamental_workflow_runner",
    "fundamental_workflow_runner",
]
