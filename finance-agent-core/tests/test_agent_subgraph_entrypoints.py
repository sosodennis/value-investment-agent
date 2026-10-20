from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import import_module

import pytest

from src.shared.kernel.workflow_contracts import WorkflowNodeResult


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


class _FakeIntentOrchestrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_extraction(self, state: object) -> WorkflowNodeResult:
        del state
        self.calls.append("run_extraction")
        return WorkflowNodeResult(update={}, goto="END")


async def test_agent_subgraph_entrypoints_build_with_fake_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_adapter = _FakeWorkflowAdapter()
    intent_wiring = import_module("src.agents.intent.application.wiring")
    fake_intent_orchestrator = _FakeIntentOrchestrator()
    monkeypatch.setattr(
        intent_wiring,
        "get_intent_orchestrator",
        lambda: fake_intent_orchestrator,
    )

    from src.agents.debate.application.subgraph import build_debate_subgraph
    from src.agents.fundamental.application.subgraph import build_fundamental_subgraph
    from src.agents.intent.application.subgraph import build_intent_extraction_subgraph
    from src.agents.news.application.subgraph import build_financial_news_subgraph
    from src.agents.technical.application.subgraph import build_technical_subgraph

    node_adapters = {
        "src.workflow.nodes.fundamental_analysis.nodes": (
            "get_fundamental_workflow_runner",
        ),
        "src.workflow.nodes.financial_news_research.nodes": (
            "get_news_workflow_runner",
        ),
        "src.workflow.nodes.technical_analysis.nodes": (
            "get_technical_workflow_runner",
        ),
        "src.workflow.nodes.debate.nodes": ("get_debate_workflow_runner",),
    }
    for module_name, getter_names in node_adapters.items():
        node_module = import_module(module_name)
        for getter_name in getter_names:
            monkeypatch.setattr(
                node_module, getter_name, lambda adapter=fake_adapter: adapter
            )

    intent_nodes = import_module("src.workflow.nodes.intent_extraction.nodes")
    monkeypatch.setattr(intent_nodes, "intent_orchestrator", fake_intent_orchestrator)

    graphs = [
        build_intent_extraction_subgraph(),
        build_fundamental_subgraph(),
        build_financial_news_subgraph(),
        build_technical_subgraph(),
        build_debate_subgraph(),
    ]

    for graph in graphs:
        assert hasattr(graph, "invoke")
        assert graph.get_input_schema() is not None
        assert graph.get_output_schema() is not None
        await graph.ainvoke({})

    assert fake_intent_orchestrator.calls == ["run_extraction"]
    assert {
        "run_financial_health",
        "run_search",
        "run_data_fetch",
        "run_debate_aggregator",
    } <= set(fake_adapter.calls)
