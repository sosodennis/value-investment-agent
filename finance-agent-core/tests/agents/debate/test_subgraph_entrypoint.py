from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from src.agents.debate.workflow.state import DebateInput, DebateOutput
from src.shared.kernel.workflow_contracts import WorkflowNodeResult


class _FakeWorkflowAdapter:
    def __init__(self, routes: Mapping[str, str | list[str]] | None = None) -> None:
        self.calls: list[str] = []
        self.routes = routes or {}

    def __getattr__(
        self, method_name: str
    ) -> Callable[..., Awaitable[WorkflowNodeResult]]:
        async def run(*args: object, **kwargs: object) -> WorkflowNodeResult:
            del args, kwargs
            self.calls.append(method_name)
            return WorkflowNodeResult(
                update={}, goto=self.routes.get(method_name, "END")
            )

        return run


async def test_debate_subgraph_entrypoint_builds_and_invokes_with_fake_adapter() -> (
    None
):
    from src.agents.debate.entrypoint import build_debate_subgraph

    fake_adapter = _FakeWorkflowAdapter(
        {
            "run_debate_aggregator": "fact_extractor",
            "run_fact_extractor": ["r1_bull", "r1_bear"],
            "run_r1_bull": "r1_moderator",
            "run_r1_bear": "r1_moderator",
            "run_r1_moderator": "r2_bull",
            "run_r2_bull": "r2_bear",
            "run_r2_bear": "r2_moderator",
            "run_r2_moderator": "r3_bear",
            "run_r3_bear": "r3_bull",
            "run_r3_bull": "verdict",
            "run_verdict": "END",
        }
    )
    graph = build_debate_subgraph(fake_adapter)  # type: ignore[arg-type]

    assert graph.get_input_schema() is DebateInput
    assert set(graph.get_output_schema().model_fields) == set(DebateOutput.model_fields)
    await graph.ainvoke({})

    assert set(fake_adapter.calls) == {
        "run_debate_aggregator",
        "run_fact_extractor",
        "run_r1_bull",
        "run_r1_bear",
        "run_r1_moderator",
        "run_r2_bull",
        "run_r2_bear",
        "run_r2_moderator",
        "run_r3_bear",
        "run_r3_bull",
        "run_verdict",
    }


async def test_debate_subgraph_stops_when_node_routes_to_end() -> None:
    from src.agents.debate.entrypoint import build_debate_subgraph

    fake_adapter = _FakeWorkflowAdapter({"run_debate_aggregator": "END"})

    await build_debate_subgraph(fake_adapter).ainvoke({})  # type: ignore[arg-type]

    assert fake_adapter.calls == ["run_debate_aggregator"]


async def test_debate_entrypoint_uses_default_wiring(
    monkeypatch,
) -> None:
    from src.agents.debate.application import wiring
    from src.agents.debate.entrypoint import build_debate_subgraph

    fake_adapter = _FakeWorkflowAdapter({"run_debate_aggregator": "END"})
    monkeypatch.setattr(wiring, "get_debate_workflow_runner", lambda: fake_adapter)

    await build_debate_subgraph().ainvoke({})

    assert fake_adapter.calls == ["run_debate_aggregator"]
