from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from src.agents.fundamental.interface.forward_evidence_routes import (
    ForwardEvidenceResearchResponse,
    build_forward_evidence_router,
)
from src.agents.fundamental.workflow.graph import build_fundamental_workflow
from src.agents.fundamental.workflow.nodes import FundamentalWorkflowRunner
from src.agents.fundamental.workflow.state import (
    FundamentalAnalysisContext,
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
    IntentExtractionContext,
)


def build_fundamental_subgraph(
    runner: FundamentalWorkflowRunner | None = None,
) -> CompiledStateGraph:
    if runner is None:
        from src.agents.fundamental.application.wiring import (
            get_fundamental_workflow_runner,
        )

        runner = get_fundamental_workflow_runner()
    return build_fundamental_workflow(runner)


def build_default_fundamental_forward_evidence_router():
    from src.agents.fundamental.application.wiring import (
        build_default_forward_evidence_research_service,
    )

    return build_forward_evidence_router(
        build_default_forward_evidence_research_service,
    )


fundamental_forward_evidence_router = (
    build_default_fundamental_forward_evidence_router()
)


__all__ = [
    "FundamentalAnalysisContext",
    "FundamentalAnalysisInput",
    "FundamentalAnalysisOutput",
    "FundamentalAnalysisState",
    "IntentExtractionContext",
    "ForwardEvidenceResearchResponse",
    "build_fundamental_subgraph",
    "build_default_fundamental_forward_evidence_router",
    "fundamental_forward_evidence_router",
]
