from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.fundamental_service_port import (
    FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    FundamentalServiceClient,
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
        *,
        request_approval: Callable[[Mapping[str, object]], object],
    ) -> FundamentalNodeResult:
        return await self.orchestrator.run_service_valuation(
            state,
            client=self.fundamental_service_client,
            request_approval_fn=lambda payload: request_approval(payload),
            timeout_seconds=self.service_timeout_seconds,
        )


def build_fundamental_workflow_runner(
    *,
    orchestrator: FundamentalOrchestrator,
    fundamental_service_client: FundamentalServiceClient,
    service_timeout_seconds: float = FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
) -> FundamentalWorkflowRunner:
    return FundamentalWorkflowRunner(
        orchestrator=orchestrator,
        fundamental_service_client=fundamental_service_client,
        service_timeout_seconds=service_timeout_seconds,
    )
