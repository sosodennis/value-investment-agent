from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.factory import technical_workflow_runner
from src.workflow.command_adapter import command_from_result

from .subgraph_state import TechnicalAnalysisState


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_data_fetch(state)
    return command_from_result(result, end_node=END)


async def fracdiff_compute_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_fracdiff_compute(state)
    return command_from_result(result, end_node=END)


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_workflow_runner.run_semantic_translate(state)
    return command_from_result(result, end_node=END)
