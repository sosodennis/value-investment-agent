from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.wiring import get_technical_workflow_runner
from src.workflow.command_adapter import command_from_result

from .subgraph_state import TechnicalAnalysisState


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_data_fetch(state)
    return command_from_result(result, end_node=END)


async def feature_compute_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_feature_compute(state)
    return command_from_result(result, end_node=END)


async def pattern_compute_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_pattern_compute(state)
    return command_from_result(result, end_node=END)


async def alerts_compute_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_alerts_compute(state)
    return command_from_result(result, end_node=END)


async def fusion_compute_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_fusion_compute(state)
    return command_from_result(result, end_node=END)


async def verification_compute_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_verification_compute(state)
    return command_from_result(result, end_node=END)


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    technical_workflow_runner = get_technical_workflow_runner()
    result = await technical_workflow_runner.run_semantic_translate(state)
    return command_from_result(result, end_node=END)
