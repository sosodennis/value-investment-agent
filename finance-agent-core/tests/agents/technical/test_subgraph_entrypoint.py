from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.workflow.nodes.technical_analysis.subgraph_state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
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


async def test_technical_subgraph_entrypoint_builds_and_invokes_with_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.technical.application.subgraph import build_technical_subgraph
    from src.workflow.nodes.technical_analysis import nodes

    fake_adapter = _FakeWorkflowAdapter()
    monkeypatch.setattr(nodes, "get_technical_workflow_runner", lambda: fake_adapter)

    graph = build_technical_subgraph()

    assert graph.get_input_schema() is TechnicalAnalysisInput
    assert set(graph.get_output_schema().model_fields) == set(
        TechnicalAnalysisOutput.model_fields
    )
    await graph.ainvoke({})

    assert fake_adapter.calls == [
        "run_data_fetch",
        "run_feature_compute",
        "run_pattern_compute",
        "run_alerts_compute",
        "run_regime_compute",
        "run_fusion_compute",
        "run_verification_compute",
        "run_semantic_translate",
    ]
