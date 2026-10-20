from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.workflow.nodes.financial_news_research.subgraph_state import (
    FinancialNewsInput,
    FinancialNewsOutput,
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


async def test_news_subgraph_entrypoint_builds_and_invokes_with_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.news.application.subgraph import build_financial_news_subgraph
    from src.workflow.nodes.financial_news_research import nodes

    fake_adapter = _FakeWorkflowAdapter()
    monkeypatch.setattr(nodes, "get_news_workflow_runner", lambda: fake_adapter)

    graph = build_financial_news_subgraph()

    assert graph.get_input_schema() is FinancialNewsInput
    assert set(graph.get_output_schema().model_fields) == set(
        FinancialNewsOutput.model_fields
    )
    await graph.ainvoke({})

    assert fake_adapter.calls == ["run_search"]
