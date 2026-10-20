from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.workflow.state import FundamentalAnalysisState
from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.shared.kernel.workflow_routing import resolve_end_goto


class FundamentalWorkflowRunner(Protocol):
    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_model_selection(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...

    async def run_valuation(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult: ...


FundamentalNode = Callable[[FundamentalAnalysisState], Awaitable[Command[object]]]


def build_fundamental_nodes(
    runner: FundamentalWorkflowRunner,
) -> dict[str, FundamentalNode]:
    async def financial_health_node(state: FundamentalAnalysisState) -> Command[object]:
        result = await runner.run_financial_health(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto(result.goto, end_node=END),
        )

    async def model_selection_node(state: FundamentalAnalysisState) -> Command[object]:
        result = await runner.run_model_selection(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto(result.goto, end_node=END),
        )

    async def valuation_node(state: FundamentalAnalysisState) -> Command[object]:
        result = await runner.run_valuation(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto(result.goto, end_node=END),
        )

    return {
        "financial_health": financial_health_node,
        "model_selection": model_selection_node,
        "calculation": valuation_node,
    }


__all__ = [
    "FundamentalWorkflowRunner",
    "build_fundamental_nodes",
]
