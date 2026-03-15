from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.technical.application.orchestrator import (
    TechnicalNodeResult,
    TechnicalOrchestrator,
)
from src.agents.technical.application.ports import (
    ITechnicalArtifactRepository,
    ITechnicalInterpretationProvider,
)
from src.agents.technical.interface.preview_projection_service import (
    summarize_ta_for_preview,
)
from src.agents.technical.interface.serializers import build_full_report_payload
from src.agents.technical.subdomains.alerts import AlertRuntimeService
from src.agents.technical.subdomains.features import (
    FeatureRuntimeService,
    IndicatorSeriesRuntimeService,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    IMarketDataProvider,
)
from src.agents.technical.subdomains.patterns import PatternRuntimeService
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeService,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.agents.technical.subdomains.verification import VerificationRuntimeService
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
    market_data_provider: IMarketDataProvider
    interpretation_provider: ITechnicalInterpretationProvider
    feature_runtime: FeatureRuntimeService
    indicator_series_runtime: IndicatorSeriesRuntimeService
    alert_runtime: AlertRuntimeService
    pattern_runtime: PatternRuntimeService
    fusion_runtime: FusionRuntimeService
    verification_runtime: VerificationRuntimeService
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

    async def run_feature_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_feature_compute(
            state,
            feature_runtime=self.deps.feature_runtime,
            indicator_series_runtime=self.deps.indicator_series_runtime,
        )

    async def run_pattern_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_pattern_compute(
            state,
            pattern_runtime=self.deps.pattern_runtime,
        )

    async def run_alerts_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_alerts_compute(
            state,
            alert_runtime=self.deps.alert_runtime,
        )

    async def run_fusion_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_fusion_compute(
            state,
            fusion_runtime=self.deps.fusion_runtime,
        )

    async def run_verification_compute(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_verification_compute(
            state,
            verification_runtime=self.deps.verification_runtime,
        )

    async def run_semantic_translate(
        self, state: Mapping[str, object]
    ) -> TechnicalNodeResult:
        return await self.orchestrator.run_semantic_translate(
            state,
            assemble_fn=self.deps.assemble_semantic_tags_fn,
            build_full_report_payload_fn=self.deps.build_full_report_payload_fn,
            interpretation_provider=self.deps.interpretation_provider,
        )


def build_technical_workflow_runner(
    *,
    orchestrator: TechnicalOrchestrator,
    deps: TechnicalWorkflowDependencies,
) -> TechnicalWorkflowRunner:
    return TechnicalWorkflowRunner(orchestrator=orchestrator, deps=deps)
