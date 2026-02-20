from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from src.agents.debate.application.factory import debate_workflow_runner
from src.agents.debate.application.orchestrator import DebateNodeResult
from src.workflow.command_adapter import command_from_fanout_result

from .subgraph_state import DebateState


def _to_command(result: DebateNodeResult) -> Command:
    return command_from_fanout_result(result, end_node=END)


async def debate_aggregator_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_debate_aggregator(state)
    return _to_command(result)


async def fact_extractor_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_fact_extractor(state)
    return _to_command(result)


async def r1_bull_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r1_bull(state)
    return _to_command(result)


async def r1_bear_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r1_bear(state)
    return _to_command(result)


async def r1_moderator_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r1_moderator(state)
    return _to_command(result)


async def r2_bull_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r2_bull(state)
    return _to_command(result)


async def r2_bear_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r2_bear(state)
    return _to_command(result)


async def r2_moderator_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r2_moderator(state)
    return _to_command(result)


async def r3_bear_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r3_bear(state)
    return _to_command(result)


async def r3_bull_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_r3_bull(state)
    return _to_command(result)


async def verdict_node(state: DebateState) -> Command:
    result = await debate_workflow_runner.run_verdict(state)
    return _to_command(result)
