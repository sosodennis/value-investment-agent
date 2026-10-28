from __future__ import annotations

from collections.abc import Mapping

import pytest

from src.agents.fundamental.entrypoint import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    build_fundamental_subgraph,
)
from src.shared.kernel.workflow_contracts import WorkflowNodeResult


class _FakeWorkflowAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _result(self, method_name: str, next_node: str) -> WorkflowNodeResult:
        self.calls.append(method_name)
        return WorkflowNodeResult(update={}, goto=next_node)

    async def run_financial_health(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult:
        del state
        return self._result("run_financial_health", "model_selection")

    async def run_model_selection(
        self, state: Mapping[str, object]
    ) -> WorkflowNodeResult:
        del state
        return self._result("run_model_selection", "calculation")

    async def run_valuation(
        self,
        state: Mapping[str, object],
        *,
        request_approval,
    ) -> WorkflowNodeResult:
        del state, request_approval
        return self._result("run_valuation", "END")


async def test_fundamental_subgraph_entrypoint_builds_and_invokes_with_fake_adapter() -> (
    None
):
    fake_adapter = _FakeWorkflowAdapter()
    graph = build_fundamental_subgraph(fake_adapter)

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


async def test_fundamental_subgraph_entrypoint_uses_default_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.fundamental.application import wiring

    fake_adapter = _FakeWorkflowAdapter()
    monkeypatch.setattr(wiring, "get_fundamental_workflow_runner", lambda: fake_adapter)

    graph = build_fundamental_subgraph()
    await graph.ainvoke({})

    assert fake_adapter.calls == [
        "run_financial_health",
        "run_model_selection",
        "run_valuation",
    ]
