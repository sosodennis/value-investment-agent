from __future__ import annotations

from fastapi import APIRouter
from langgraph.graph.state import CompiledStateGraph

from src.agents.fundamental.interface.forward_evidence_routes import (
    ForwardEvidenceResearchResponse,
    build_forward_evidence_router,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalValuationIntentV1,
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
from src.artifacts.public import FiscalCurrentReadContext


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


def build_default_fundamental_annual_statement_router():
    from src.agents.fundamental.application.wiring import (
        build_default_annual_statement_router,
    )

    return build_default_annual_statement_router()


fundamental_annual_statement_router = (
    build_default_fundamental_annual_statement_router()
)


__all__ = [
    "FundamentalValuationIntentV1",
    "FundamentalAnalysisContext",
    "FundamentalAnalysisInput",
    "FundamentalAnalysisOutput",
    "FundamentalAnalysisState",
    "IntentExtractionContext",
    "ForwardEvidenceResearchResponse",
    "build_fundamental_subgraph",
    "build_default_fundamental_forward_evidence_router",
    "fundamental_forward_evidence_router",
    "fundamental_annual_statement_router",
    "fundamental_statement_router",
    "build_default_fiscal_artifact_current_reader",
]


def build_default_fundamental_statement_router() -> APIRouter:
    from src.agents.fundamental.application.wiring import build_default_statement_router

    return build_default_statement_router()


def build_default_fiscal_artifact_current_reader() -> FiscalCurrentReadContext:
    from src.agents.fundamental.application.wiring import (
        build_default_fiscal_artifact_current_reader as factory,
    )

    return factory()


fundamental_statement_router = build_default_fundamental_statement_router()
