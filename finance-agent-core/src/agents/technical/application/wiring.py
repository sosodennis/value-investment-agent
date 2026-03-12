from __future__ import annotations

from src.agents.technical.application.backtest_runtime_service import (
    TechnicalBacktestRuntimeService,
)
from src.agents.technical.application.factory import (
    TechnicalWorkflowDependencies,
    TechnicalWorkflowRunner,
    build_technical_orchestrator,
    build_technical_workflow_runner,
)
from src.agents.technical.application.fracdiff_runtime_service import (
    TechnicalFracdiffRuntimeService,
)
from src.agents.technical.domain.signal_policy import assemble_semantic_tags
from src.agents.technical.infrastructure.artifacts import (
    build_default_technical_artifact_repository,
)
from src.agents.technical.infrastructure.llm import TechnicalInterpretationProvider
from src.agents.technical.infrastructure.market_data import YahooMarketDataProvider


def _assemble_semantic_tags_default(*args, **kwargs):
    return assemble_semantic_tags(*args, **kwargs)


def build_default_technical_workflow_runner() -> TechnicalWorkflowRunner:
    repository = build_default_technical_artifact_repository()
    orchestrator = build_technical_orchestrator(port=repository)
    market_data_provider = YahooMarketDataProvider()
    interpretation_provider = TechnicalInterpretationProvider()
    backtest_runtime = TechnicalBacktestRuntimeService()
    fracdiff_runtime = TechnicalFracdiffRuntimeService()
    return build_technical_workflow_runner(
        orchestrator=orchestrator,
        deps=TechnicalWorkflowDependencies(
            market_data_provider=market_data_provider,
            interpretation_provider=interpretation_provider,
            backtest_runtime=backtest_runtime,
            fracdiff_runtime=fracdiff_runtime,
            assemble_semantic_tags_fn=_assemble_semantic_tags_default,
        ),
    )


_technical_workflow_runner: TechnicalWorkflowRunner | None = None


def get_technical_workflow_runner() -> TechnicalWorkflowRunner:
    global _technical_workflow_runner
    if _technical_workflow_runner is None:
        _technical_workflow_runner = build_default_technical_workflow_runner()
    return _technical_workflow_runner


__all__ = [
    "TechnicalWorkflowRunner",
    "build_default_technical_workflow_runner",
    "get_technical_workflow_runner",
]
