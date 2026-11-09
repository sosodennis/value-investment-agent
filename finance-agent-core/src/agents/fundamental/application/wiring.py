from __future__ import annotations

from src.agents.fundamental.application.workflow_orchestrator.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.capabilities.forward_evidence.research_service import (
    ForwardEvidenceResearchService,
)
from src.agents.fundamental.infrastructure import HttpFundamentalServiceClient
from src.llm_provider.entrypoint import get_default_model_route, get_llm_provider
from src.search import get_search_client


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    orchestrator = build_fundamental_orchestrator()
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fundamental_service_client=HttpFundamentalServiceClient(),
    )


_fundamental_workflow_runner: FundamentalWorkflowRunner | None = None


def get_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    global _fundamental_workflow_runner
    if _fundamental_workflow_runner is None:
        _fundamental_workflow_runner = build_default_fundamental_workflow_runner()
    return _fundamental_workflow_runner


def build_default_forward_evidence_research_service() -> ForwardEvidenceResearchService:
    return ForwardEvidenceResearchService(
        fundamental_service_client=HttpFundamentalServiceClient(),
        search_fn=get_search_client().search_web,
        llm_provider=get_llm_provider(),
        llm_route=get_default_model_route(),
    )


__all__ = [
    "FundamentalWorkflowRunner",
    "build_default_fundamental_workflow_runner",
    "get_fundamental_workflow_runner",
    "build_default_forward_evidence_research_service",
]
