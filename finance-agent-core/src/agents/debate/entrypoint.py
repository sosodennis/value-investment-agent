from langgraph.graph.state import CompiledStateGraph

from src.agents.debate.application.ports import DebateWorkflowPort
from src.agents.debate.workflow.graph import build_debate_workflow
from src.agents.debate.workflow.state import DebateInput, DebateOutput


def build_debate_subgraph(
    runner: DebateWorkflowPort | None = None,
) -> CompiledStateGraph:
    if runner is None:
        from src.agents.debate.application.wiring import get_debate_workflow_runner

        runner = get_debate_workflow_runner()
    return build_debate_workflow(runner)


__all__ = ["DebateInput", "DebateOutput", "build_debate_subgraph"]
