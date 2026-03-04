from __future__ import annotations

from src.agents.debate.application.factory import (
    DebateWorkflowRunner,
    build_debate_workflow_runner,
)
from src.agents.debate.application.orchestrator import DebateOrchestrator
from src.agents.debate.infrastructure.artifacts.debate_artifact_repository import (
    debate_artifact_repository,
)
from src.agents.debate.infrastructure.artifacts.debate_source_reader_repository import (
    debate_source_reader_repository,
)
from src.agents.debate.infrastructure.market_data.capm_market_data_provider import (
    get_current_risk_free_rate,
    get_dynamic_payoff_map,
)
from src.agents.debate.infrastructure.sycophancy.sycophancy_detector_provider import (
    get_sycophancy_detector_provider,
)
from src.agents.debate.interface.mappers import summarize_debate_for_preview
from src.infrastructure.llm.provider import get_llm
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    OUTPUT_KIND_DEBATE,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def _build_debate_output_artifact(
    summary: str,
    preview: JSONObject,
    report_id: str | None,
) -> AgentOutputArtifactPayload | None:
    reference = None
    if report_id:
        reference = ArtifactReference(
            artifact_id=report_id,
            download_url=f"/api/artifacts/{report_id}",
            type=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        )

    return build_artifact_payload(
        kind=OUTPUT_KIND_DEBATE,
        summary=summary,
        preview=preview,
        reference=reference,
    )


def build_debate_orchestrator() -> DebateOrchestrator:
    return DebateOrchestrator(
        source_reader=debate_source_reader_repository,
        artifact_port=debate_artifact_repository,
        get_llm_fn=lambda: get_llm(),
        get_sycophancy_detector_fn=lambda: get_sycophancy_detector_provider(),
        summarize_preview_fn=summarize_debate_for_preview,
        build_output_artifact_fn=_build_debate_output_artifact,
        get_risk_free_rate_fn=get_current_risk_free_rate,
        get_payoff_map_fn=get_dynamic_payoff_map,
    )


_workflow_runner: DebateWorkflowRunner | None = None


def get_debate_workflow_runner() -> DebateWorkflowRunner:
    global _workflow_runner
    if _workflow_runner is None:
        _workflow_runner = build_debate_workflow_runner(build_debate_orchestrator())
    return _workflow_runner
