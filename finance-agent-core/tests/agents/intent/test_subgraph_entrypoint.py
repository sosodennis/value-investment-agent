from __future__ import annotations

import pytest

from src.agents.intent.application.ports import IntentRuntimePorts
from src.agents.intent.workflow.state import (
    IntentExtractionInput,
    IntentExtractionOutput,
)
from src.llm_provider.entrypoint import ModelRoute
from src.shared.kernel.workflow_contracts import WorkflowNodeResult


class _FakeIntentOrchestrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_extraction(self, state: object) -> WorkflowNodeResult:
        del state
        self.calls.append("run_extraction")
        return WorkflowNodeResult(update={}, goto="END")


class _FakeClarificationOrchestrator:
    def __init__(self) -> None:
        self.resolution_args: dict[str, object] | None = None

    def build_clarification_interrupt_payload(
        self, state: object
    ) -> tuple[dict[str, object], list[dict[str, str]]]:
        del state
        candidates = [{"symbol": "AAPL", "name": "Apple Inc."}]
        return {"reason": "Choose the correct ticker."}, candidates

    def build_clarification_resolution_update(
        self,
        *,
        user_input: object,
        candidates_raw: object,
        interrupt_payload_dump: dict[str, object],
    ) -> dict[str, object]:
        self.resolution_args = {
            "user_input": user_input,
            "candidates_raw": candidates_raw,
            "interrupt_payload_dump": interrupt_payload_dump,
        }
        return {"intent_extraction": {"status": "resolved", "resolved_ticker": "AAPL"}}


async def test_intent_subgraph_entrypoint_builds_and_invokes_with_fake_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_orchestrator = _FakeIntentOrchestrator()
    runtime_ports = IntentRuntimePorts(
        llm_provider=None,  # type: ignore[arg-type]
        llm_route=ModelRoute(alias="openrouter-default"),
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


async def test_intent_entrypoint_uses_default_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.intent.application import wiring
    from src.agents.intent.entrypoint import build_intent_extraction_graph

    fake_orchestrator = _FakeIntentOrchestrator()
    monkeypatch.setattr(wiring, "get_intent_orchestrator", lambda: fake_orchestrator)

    graph = build_intent_extraction_graph()
    await graph.ainvoke({})

    assert fake_orchestrator.calls == ["run_extraction"]


async def test_clarification_resume_resolves_selected_ticker() -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command

    from src.agents.intent.workflow.nodes import build_intent_nodes
    from src.agents.intent.workflow.state import IntentExtractionState

    fake_orchestrator = _FakeClarificationOrchestrator()
    builder = StateGraph(IntentExtractionState)
    builder.add_node("clarifying", build_intent_nodes(fake_orchestrator)["clarifying"])
    builder.add_edge(START, "clarifying")
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "intent-clarification-resume-test"}}

    await graph.ainvoke(
        {
            "user_query": None,
            "intent_extraction": {},
            "messages": [],
            "workflow_activity_updates": {},
            "active_activity_id": "clarifying",
            "workflow_activity_statuses": {},
            "error_logs": [],
        },
        config=config,
    )
    result = await graph.ainvoke(
        Command(resume={"selected_symbol": "AAPL"}), config=config
    )

    assert result["intent_extraction"] == {
        "status": "resolved",
        "resolved_ticker": "AAPL",
    }
    assert fake_orchestrator.resolution_args == {
        "user_input": {"selected_symbol": "AAPL"},
        "candidates_raw": [{"symbol": "AAPL", "name": "Apple Inc."}],
        "interrupt_payload_dump": {"reason": "Choose the correct ticker."},
    }
