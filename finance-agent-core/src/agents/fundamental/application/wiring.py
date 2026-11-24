from __future__ import annotations

from src.agents.fundamental.application.workflow_orchestrator.factory import (
    FundamentalWorkflowRunner,
    build_fundamental_orchestrator,
    build_fundamental_workflow_runner,
)
from src.agents.fundamental.capabilities.forward_evidence import (
    ForwardEvidenceResearchService,
)
from src.agents.fundamental.infrastructure import (
    HttpFundamentalServiceClient,
    load_fundamental_release_selector,
)
from src.agents.fundamental.infrastructure.valuation_revision_source_reader import (
    ArtifactFundamentalRevisionSourceReader,
)
from src.artifacts.public import build_default_artifact_service
from src.auth.entrypoint import get_ownership_service
from src.llm_provider.entrypoint import get_default_model_route, get_llm_provider
from src.search import get_search_client


def build_default_fundamental_workflow_runner() -> FundamentalWorkflowRunner:
    artifacts = build_default_artifact_service()
    orchestrator = build_fundamental_orchestrator(artifact_storage=artifacts)
    return build_fundamental_workflow_runner(
        orchestrator=orchestrator,
        fundamental_service_client=HttpFundamentalServiceClient(),
        release_selector=load_fundamental_release_selector(),
        revision_source_reader=ArtifactFundamentalRevisionSourceReader(
            artifacts=artifacts, owns_thread=_owns_thread
        ),
    )


async def _owns_thread(subject_id: str, thread_id: str) -> bool:
    return await get_ownership_service().owns(
        user_id=subject_id, resource_type="thread", resource_id=thread_id
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


def build_default_annual_statement_router():
    from contextlib import asynccontextmanager

    from src.agents.fundamental.application.annual_statement_reader import (
        AnnualStatementReaderService,
    )
    from src.agents.fundamental.composition.annual_statement_routes import (
        build_annual_statement_router,
    )
    from src.agents.fundamental.infrastructure.annual_statement_reader_config import (
        load_annual_statement_reader_bindings,
    )

    @asynccontextmanager
    async def factory():
        client = HttpFundamentalServiceClient()
        try:
            yield AnnualStatementReaderService(
                client=client,
                artifacts=build_default_artifact_service(),
                bindings=load_annual_statement_reader_bindings(),
                owns_thread=_owns_scoped_thread,
                claim_thread=_claim_scoped_thread,
            )
        finally:
            await client.aclose()

    return build_annual_statement_router(factory)


async def _owns_scoped_thread(
    subject_id: str, thread_id: str, organization_id: str
) -> bool:
    return await get_ownership_service().owns(
        user_id=subject_id,
        resource_type="thread",
        resource_id=thread_id,
        organization_id=organization_id,
    )


async def _claim_scoped_thread(
    subject_id: str, thread_id: str, organization_id: str
) -> bool:
    return await get_ownership_service().claim(
        user_id=subject_id,
        resource_type="thread",
        resource_id=thread_id,
        organization_id=organization_id,
    )
