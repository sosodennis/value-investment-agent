from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.fundamental_service_port import (
    FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    FundamentalReleaseSelector,
    FundamentalServiceClient,
)
from src.agents.fundamental.application.valuation_revision_port import (
    FundamentalRevisionSourceReaderPort,
)
from src.agents.fundamental.application.workflow_orchestrator.orchestrator import (
    FundamentalNodeResult,
    FundamentalOrchestrator,
)
from src.agents.fundamental.capabilities.model_selection.public import (
    select_valuation_model,
)
from src.artifacts.public import ArtifactStoragePort, build_default_artifact_service


def build_fundamental_orchestrator(
    *, artifact_storage: ArtifactStoragePort | None = None
) -> FundamentalOrchestrator:
    return FundamentalOrchestrator(
        artifact_storage=(
            artifact_storage
            if artifact_storage is not None
            else build_default_artifact_service()
        )
    )


@dataclass(frozen=True)
class FundamentalWorkflowRunner:
    orchestrator: FundamentalOrchestrator
    fundamental_service_client: FundamentalServiceClient
    service_timeout_seconds: float = FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS
    release_selector: FundamentalReleaseSelector | None = None
    revision_source_reader: FundamentalRevisionSourceReaderPort | None = None

    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_financial_health(state)

    async def run_model_selection(
        self, state: Mapping[str, object]
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_model_selection(
            state,
            select_valuation_model_fn=select_valuation_model,
        )

    async def run_valuation(
        self,
        state: Mapping[str, object],
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_service_valuation(
            state,
            client=self.fundamental_service_client,
            timeout_seconds=self.service_timeout_seconds,
            release_selector=self.release_selector,
            revision_source_reader=self.revision_source_reader,
        )


def build_fundamental_workflow_runner(
    *,
    orchestrator: FundamentalOrchestrator,
    fundamental_service_client: FundamentalServiceClient,
    service_timeout_seconds: float = FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    release_selector: FundamentalReleaseSelector | None = None,
    revision_source_reader: FundamentalRevisionSourceReaderPort | None = None,
) -> FundamentalWorkflowRunner:
    return FundamentalWorkflowRunner(
        orchestrator=orchestrator,
        fundamental_service_client=fundamental_service_client,
        service_timeout_seconds=service_timeout_seconds,
        release_selector=release_selector,
        revision_source_reader=revision_source_reader,
    )
