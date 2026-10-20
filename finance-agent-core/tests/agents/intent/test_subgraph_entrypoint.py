from __future__ import annotations

import pytest

from src.shared.kernel.workflow_contracts import WorkflowNodeResult
from src.workflow.nodes.intent_extraction.subgraph_state import (
    IntentExtractionInput,
    IntentExtractionOutput,
)


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
    from src.agents.intent.application import wiring
    from src.agents.intent.application.subgraph import build_intent_extraction_subgraph

    fake_orchestrator = _FakeIntentOrchestrator()
    monkeypatch.setattr(wiring, "get_intent_orchestrator", lambda: fake_orchestrator)

    from src.workflow.nodes import intent_extraction

    monkeypatch.setattr(
        intent_extraction.nodes, "intent_orchestrator", fake_orchestrator
    )

    graph = build_intent_extraction_subgraph()

    assert graph.get_input_schema() is IntentExtractionInput
    assert set(graph.get_output_schema().model_fields) == set(
        IntentExtractionOutput.model_fields
    )
    await graph.ainvoke({})

    assert fake_orchestrator.calls == ["run_extraction"]
