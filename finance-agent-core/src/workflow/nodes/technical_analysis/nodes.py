from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.factory import technical_workflow_runner

from .subgraph_state import TechnicalAnalysisState


def _resolve_goto(target: str) -> str:
    return END if target == "END" else target


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_data_fetch(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def fracdiff_compute_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_fracdiff_compute(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_semantic_translate(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))
