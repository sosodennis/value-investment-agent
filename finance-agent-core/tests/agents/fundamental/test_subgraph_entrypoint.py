from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.workflow.nodes.fundamental_analysis.subgraph_state import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
)


class _FakeWorkflowAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(
        self, method_name: str
    ) -> Callable[..., Awaitable[WorkflowNodeResult]]:
        async def run(*args: object, **kwargs: object) -> WorkflowNodeResult:
            del args, kwargs
            self.calls.append(method_name)
            return WorkflowNodeResult(update={}, goto="END")

        return run


async def test_fundamental_subgraph_entrypoint_builds_and_invokes_with_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.fundamental.application.subgraph import build_fundamental_subgraph
    from src.workflow.nodes.fundamental_analysis import nodes

    fake_adapter = _FakeWorkflowAdapter()
    monkeypatch.setattr(nodes, "get_fundamental_workflow_runner", lambda: fake_adapter)

    graph = build_fundamental_subgraph()

    assert graph.get_input_schema() is FundamentalAnalysisInput
    assert set(graph.get_output_schema().model_fields) == set(
        FundamentalAnalysisOutput.model_fields
    )
    await graph.ainvoke({})

    assert fake_adapter.calls == [
        "run_financial_health",
        "run_model_selection",
        "run_valuation",
    ]
