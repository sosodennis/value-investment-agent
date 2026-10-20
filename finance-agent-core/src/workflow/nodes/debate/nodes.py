"""Compatibility imports; debate node ownership lives in the agent package."""

from langgraph.types import Command

from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.nodes import build_debate_nodes
from src.agents.debate.workflow.state import DebateState


async def _run(node_name: str, state: DebateState) -> Command:
    node = build_debate_nodes(get_debate_workflow_runner())[node_name]
    return await node(state)


async def debate_aggregator_node(state: DebateState) -> Command:
    return await _run("debate_aggregator", state)


async def fact_extractor_node(state: DebateState) -> Command:
    return await _run("fact_extractor", state)


async def r1_bull_node(state: DebateState) -> Command:
    return await _run("r1_bull", state)


async def r1_bear_node(state: DebateState) -> Command:
    return await _run("r1_bear", state)


async def r1_moderator_node(state: DebateState) -> Command:
    return await _run("r1_moderator", state)


async def r2_bull_node(state: DebateState) -> Command:
    return await _run("r2_bull", state)


async def r2_bear_node(state: DebateState) -> Command:
    return await _run("r2_bear", state)


async def r2_moderator_node(state: DebateState) -> Command:
    return await _run("r2_moderator", state)


async def r3_bull_node(state: DebateState) -> Command:
    return await _run("r3_bull", state)


async def r3_bear_node(state: DebateState) -> Command:
    return await _run("r3_bear", state)


async def verdict_node(state: DebateState) -> Command:
    return await _run("verdict", state)
