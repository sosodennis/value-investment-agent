from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.technical.application.orchestrator import (
    TechnicalNodeResult,
    TechnicalOrchestrator,
)
from src.agents.technical.application.ports import (
    ITechnicalArtifactRepository,
    ITechnicalBacktestRuntime,
    ITechnicalFracdiffRuntime,
    ITechnicalInterpretationProvider,
    ITechnicalMarketDataProvider,
)
from src.agents.technical.domain.signal_policy import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.agents.technical.interface.preview_projection_service import (
    summarize_ta_for_preview,
)
from src.agents.technical.interface.serializers import build_full_report_payload
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_TA_FULL_REPORT,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
)
from src.shared.kernel.types import JSONObject


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


def build_technical_orchestrator(
    *, port: ITechnicalArtifactRepository
) -> TechnicalOrchestrator:
    return TechnicalOrchestrator(
        port=port,
        summarize_preview=summarize_ta_for_preview,
        build_progress_artifact=_build_progress_artifact,
        build_semantic_output_artifact=_build_semantic_output_artifact,
    )


@dataclass(frozen=True)
class TechnicalWorkflowDependencies:
    market_data_provider: ITechnicalMarketDataProvider
    interpretation_provider: ITechnicalInterpretationProvider
    backtest_runtime: ITechnicalBacktestRuntime
    fracdiff_runtime: ITechnicalFracdiffRuntime
    assemble_semantic_tags_fn: Callable[
        [SemanticTagPolicyInput], SemanticTagPolicyResult
    ]
    build_full_report_payload_fn: Callable[..., JSONObject] = build_full_report_payload


@dataclass(frozen=True)
class TechnicalWorkflowRunner:
    orchestrator: TechnicalOrchestrator
    deps: TechnicalWorkflowDependencies

    async def run_data_fetch(self, state: Mapping[str, object]) -> TechnicalNodeResult:
        return await self.orchestrator.run_data_fetch(
            state,
            market_data_provider=self.deps.market_data_provider,
        )

    async def run_fracdiff_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_fracdiff_compute(
            state,
            fracdiff_runtime=self.deps.fracdiff_runtime,
        )

    async def run_semantic_translate(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_semantic_translate(
            state,
            assemble_fn=self.deps.assemble_semantic_tags_fn,
            build_full_report_payload_fn=self.deps.build_full_report_payload_fn,
            fracdiff_runtime=self.deps.fracdiff_runtime,
            market_data_provider=self.deps.market_data_provider,
            interpretation_provider=self.deps.interpretation_provider,
            backtest_runtime=self.deps.backtest_runtime,
        )


def build_technical_workflow_runner(
    *,
    orchestrator: TechnicalOrchestrator,
    deps: TechnicalWorkflowDependencies,
) -> TechnicalWorkflowRunner:
    return TechnicalWorkflowRunner(orchestrator=orchestrator, deps=deps)
