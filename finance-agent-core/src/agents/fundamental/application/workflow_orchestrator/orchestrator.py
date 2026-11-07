from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
)
from src.agents.fundamental.application.workflow_orchestrator.financial_health_flow import (
    run_financial_health_flow,
)
from src.agents.fundamental.application.workflow_orchestrator.model_selection_flow import (
    run_model_selection_flow,
)
from src.agents.fundamental.application.workflow_orchestrator.service_valuation_flow import (
    run_service_valuation_flow,
)
from src.agents.fundamental.capabilities.model_selection.public import (
    FundamentalSelectionReport,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

FundamentalNodeResult = WorkflowNodeResult


@dataclass(frozen=True)
class FundamentalOrchestrator:
    """Coordinate the typed Fundamental caller workflow."""

    async def run_financial_health(
        self,
        state: Mapping[str, object],
    ) -> FundamentalNodeResult:
        return await run_financial_health_flow(self, state)

    async def run_model_selection(
        self,
        state: Mapping[str, object],
        *,
        select_valuation_model_fn: Callable[
            [CompanyProfile, list[FundamentalSelectionReport]], object
        ],
    ) -> FundamentalNodeResult:
        return await run_model_selection_flow(
            self,
            state,
            select_valuation_model_fn=select_valuation_model_fn,
        )

    async def run_service_valuation(
        self,
        state: Mapping[str, object],
        *,
        client: FundamentalServiceClient,
        request_approval_fn: Callable[[JSONObject], object],
        timeout_seconds: float = 10.0,
    ) -> FundamentalNodeResult:
        """Run caller-owned approval around the stateless Fundamental service."""

        return await run_service_valuation_flow(
            self,
            state,
            client=client,
            request_approval_fn=request_approval_fn,
            timeout_seconds=timeout_seconds,
        )
