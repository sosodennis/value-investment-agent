from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.workflow.state import TechnicalAnalysisState
from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.shared.kernel.workflow_routing import resolve_end_goto

TechnicalNode = Callable[[TechnicalAnalysisState], Awaitable[Command]]


class TechnicalWorkflowRunnerPort(Protocol):
    async def run_data_fetch(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_feature_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_pattern_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_alerts_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_regime_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_fusion_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_verification_compute(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_semantic_translate(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...


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


def build_technical_nodes(
    runner: TechnicalWorkflowRunnerPort,
) -> dict[str, TechnicalNode]:
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
