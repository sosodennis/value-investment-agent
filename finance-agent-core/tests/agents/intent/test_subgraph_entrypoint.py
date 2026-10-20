from __future__ import annotations

import pytest

from src.agents.intent.application.ports import IntentRuntimePorts
from src.agents.intent.workflow.state import (
    IntentExtractionInput,
    IntentExtractionOutput,
)
from src.shared.kernel.workflow_contracts import WorkflowNodeResult


class _FakeIntentOrchestrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_extraction(self, state: object) -> WorkflowNodeResult:
        del state
        self.calls.append("run_extraction")
        return WorkflowNodeResult(update={}, goto="END")


async def test_intent_subgraph_entrypoint_builds_and_invokes_with_fake_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_orchestrator = _FakeIntentOrchestrator()
    runtime_ports = IntentRuntimePorts(
        llm_provider=lambda timeout: None,  # type: ignore[arg-type]
        search_ticker=lambda query: None,  # type: ignore[arg-type]
        web_search=lambda query: None,  # type: ignore[arg-type]
        company_profile=lambda ticker: None,  # type: ignore[arg-type]
    )
    from src.agents.intent.application import factory

    monkeypatch.setattr(
        factory,
        "build_intent_orchestrator",
        lambda *, runtime_ports: fake_orchestrator,  # type: ignore[assignment]
    )
    from src.agents.intent.entrypoint import build_intent_extraction_graph

    graph = build_intent_extraction_graph(runtime_ports)

    assert graph.get_input_schema() is IntentExtractionInput
    assert set(graph.get_output_schema().model_fields) == set(
        IntentExtractionOutput.model_fields
    )
    await graph.ainvoke({})

    assert fake_orchestrator.calls == ["run_extraction"]
