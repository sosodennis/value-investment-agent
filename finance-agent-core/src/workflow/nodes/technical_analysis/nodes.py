from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.orchestrator import TechnicalOrchestrator
from src.agents.technical.data.ports import technical_artifact_port
from src.agents.technical.data.tools import (
    CombinedBacktester,
    WalkForwardOptimizer,
    calculate_fd_bollinger,
    calculate_fd_macd,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_z_score,
    fetch_daily_ohlcv,
    fetch_risk_free_series,
    format_backtest_for_llm,
    format_wfa_for_llm,
    generate_interpretation,
)
from src.agents.technical.domain.policies import assemble_semantic_tags
from src.agents.technical.interface.mappers import summarize_ta_for_preview
from src.agents.technical.interface.serializers import build_full_report_payload
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_TA_FULL_REPORT,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
)

from .subgraph_state import TechnicalAnalysisState


def _build_progress_artifact(
    summary: str, preview: dict[str, object]
) -> dict[str, object]:
    return build_artifact_payload(
        kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
        summary=summary,
        preview=preview,
        reference=None,
    )


def _build_semantic_output_artifact(
    summary: str, preview: dict[str, object], report_id: str
) -> dict[str, object]:
    return build_artifact_payload(
        kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
        summary=summary,
        preview=preview,
        reference=ArtifactReference(
            artifact_id=report_id,
            download_url=f"/api/artifacts/{report_id}",
            type=ARTIFACT_KIND_TA_FULL_REPORT,
        ),
    )


technical_orchestrator = TechnicalOrchestrator(
    port=technical_artifact_port,
    summarize_preview=summarize_ta_for_preview,
    build_progress_artifact=_build_progress_artifact,
    build_semantic_output_artifact=_build_semantic_output_artifact,
)


def _resolve_goto(target: str) -> str:
    return END if target == "END" else target


def _with_done_status_message(update: dict[str, object]) -> dict[str, object]:
    output = dict(update)
    output["messages"] = [
        AIMessage(
            content="",
            additional_kwargs={
                "type": "technical_analysis",
                "agent_id": "technical_analysis",
                "status": "done",
            },
        )
    ]
    return output


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_orchestrator.run_data_fetch(
        state,
        fetch_daily_ohlcv_fn=lambda ticker: fetch_daily_ohlcv(ticker, period="5y"),
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def fracdiff_compute_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_orchestrator.run_fracdiff_compute(
        state,
        calculate_rolling_fracdiff_fn=calculate_rolling_fracdiff,
        compute_z_score_fn=compute_z_score,
        calculate_rolling_z_score_fn=calculate_rolling_z_score,
        calculate_fd_bollinger_fn=calculate_fd_bollinger,
        calculate_statistical_strength_fn=calculate_statistical_strength,
        calculate_fd_macd_fn=calculate_fd_macd,
        calculate_fd_obv_fn=calculate_fd_obv,
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    result = await technical_orchestrator.run_semantic_translate(
        state,
        assemble_fn=assemble_semantic_tags,
        build_full_report_payload_fn=build_full_report_payload,
        generate_interpretation_fn=generate_interpretation,
        calculate_statistical_strength_fn=calculate_statistical_strength,
        calculate_fd_bollinger_fn=calculate_fd_bollinger,
        calculate_fd_obv_fn=calculate_fd_obv,
        fetch_risk_free_series_fn=fetch_risk_free_series,
        backtester_factory=CombinedBacktester,
        format_backtest_for_llm_fn=format_backtest_for_llm,
        wfa_optimizer_factory=WalkForwardOptimizer,
        format_wfa_for_llm_fn=format_wfa_for_llm,
    )
    update = _with_done_status_message(result.update)
    return Command(update=update, goto=_resolve_goto(result.goto))
