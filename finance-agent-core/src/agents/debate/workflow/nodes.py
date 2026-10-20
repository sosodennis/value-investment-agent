from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END
from langgraph.types import Command

from src.agents.debate.application.ports import DebateWorkflowPort
from src.shared.kernel.workflow_contracts import WorkflowFanoutNodeResult
from src.shared.kernel.workflow_routing import resolve_end_goto_fanout

from .state import DebateState

Node = Callable[[DebateState], Awaitable[Command]]


def _adapt(
    call: Callable[[DebateState], Awaitable[WorkflowFanoutNodeResult]],
) -> Node:
    async def node(state: DebateState) -> Command:
        result = await call(state)
        return Command(
            update=result.update,
            goto=resolve_end_goto_fanout(result.goto, end_node=END),
        )

    return node


def build_debate_nodes(runner: DebateWorkflowPort) -> dict[str, Node]:
    return {
        "debate_aggregator": _adapt(runner.run_debate_aggregator),
        "fact_extractor": _adapt(runner.run_fact_extractor),
        "r1_bull": _adapt(runner.run_r1_bull),
        "r1_bear": _adapt(runner.run_r1_bear),
        "r1_moderator": _adapt(runner.run_r1_moderator),
        "r2_bull": _adapt(runner.run_r2_bull),
        "r2_bear": _adapt(runner.run_r2_bear),
        "r2_moderator": _adapt(runner.run_r2_moderator),
        "r3_bull": _adapt(runner.run_r3_bull),
        "r3_bear": _adapt(runner.run_r3_bear),
        "verdict": _adapt(runner.run_verdict),
    }
