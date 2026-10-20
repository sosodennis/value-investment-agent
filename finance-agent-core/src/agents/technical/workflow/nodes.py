from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.factory import TechnicalWorkflowRunner
from src.agents.technical.workflow.state import TechnicalAnalysisState
from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.shared.kernel.workflow_routing import resolve_end_goto

TechnicalNode = Callable[[TechnicalAnalysisState], Awaitable[Command]]


def _adapt(
    call: Callable[[TechnicalAnalysisState], Awaitable[WorkflowNodeResult]],
) -> TechnicalNode:
    async def node(state: TechnicalAnalysisState) -> Command:
        result = await call(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto(result.goto, end_node=END),
        )

    return node


def build_technical_nodes(runner: TechnicalWorkflowRunner) -> dict[str, TechnicalNode]:
    return {
        "data_fetch": _adapt(runner.run_data_fetch),
        "feature_compute": _adapt(runner.run_feature_compute),
        "pattern_compute": _adapt(runner.run_pattern_compute),
        "alerts_compute": _adapt(runner.run_alerts_compute),
        "regime_compute": _adapt(runner.run_regime_compute),
        "fusion_compute": _adapt(runner.run_fusion_compute),
        "verification_compute": _adapt(runner.run_verification_compute),
        "semantic_translate": _adapt(runner.run_semantic_translate),
    }
