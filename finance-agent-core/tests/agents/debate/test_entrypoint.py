from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.agents.debate.workflow.state import DebateInput, DebateOutput
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


async def test_debate_subgraph_entrypoint_builds_and_invokes_with_fake_adapter() -> (
    None
):
    from src.agents.debate.entrypoint import build_debate_subgraph

    fake_adapter = _FakeWorkflowAdapter()
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
