from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.technical.application.ports import (
    ITechnicalArtifactRepository,
    ITechnicalInterpretationProvider,
)
from src.agents.technical.application.use_cases import (
    run_alerts_compute_use_case,
    run_data_fetch_use_case,
    run_feature_compute_use_case,
    run_fusion_compute_use_case,
    run_pattern_compute_use_case,
    run_regime_compute_use_case,
    run_semantic_translate_use_case,
    run_verification_compute_use_case,
)
from src.agents.technical.subdomains.alerts import AlertRuntimeService
from src.agents.technical.subdomains.features import (
    FeatureRuntimeService,
    IndicatorSeriesRuntimeService,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    IMarketDataProvider,
)
from src.agents.technical.subdomains.patterns import PatternRuntimeService
from src.agents.technical.subdomains.regime import RegimeRuntimeService
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeService,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.agents.technical.subdomains.verification import VerificationRuntimeService
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeaturePackArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
)
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

TechnicalNodeResult = WorkflowNodeResult


@dataclass(frozen=True)
class _DataFetchRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def save_price_series(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_price_series(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def save_timeseries_bundle(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_timeseries_bundle(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _VerificationComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_timeseries_bundle(
        self,
        artifact_id: str,
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.port.load_timeseries_bundle(artifact_id)

    async def save_verification_report(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_verification_report(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def save_chart_data(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_chart_data(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _FeatureComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_timeseries_bundle(
        self,
        artifact_id: str,
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.port.load_timeseries_bundle(artifact_id)

    async def save_feature_pack(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_feature_pack(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def save_indicator_series(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_indicator_series(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _PatternComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_timeseries_bundle(
        self,
        artifact_id: str,
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.port.load_timeseries_bundle(artifact_id)

    async def save_pattern_pack(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_pattern_pack(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _AlertsComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_indicator_series(
        self,
        artifact_id: str,
    ) -> TechnicalIndicatorSeriesArtifactData | None:
        return await self.port.load_indicator_series(artifact_id)

    async def load_pattern_pack(
        self,
        artifact_id: str,
    ) -> TechnicalPatternPackArtifactData | None:
        return await self.port.load_pattern_pack(artifact_id)

    async def save_alerts(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_alerts(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _FusionComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_timeseries_bundle(
        self,
        artifact_id: str,
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.port.load_timeseries_bundle(artifact_id)

    async def load_feature_pack(
        self,
        artifact_id: str,
    ) -> TechnicalFeaturePackArtifactData | None:
        return await self.port.load_feature_pack(artifact_id)

    async def load_pattern_pack(
        self,
        artifact_id: str,
    ) -> TechnicalPatternPackArtifactData | None:
        return await self.port.load_pattern_pack(artifact_id)

    async def load_regime_pack(
        self,
        artifact_id: str,
    ) -> TechnicalRegimePackArtifactData | None:
        return await self.port.load_regime_pack(artifact_id)

    async def save_fusion_report(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_fusion_report(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def save_direction_scorecard(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_direction_scorecard(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class _RegimeComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_timeseries_bundle(
        self,
        artifact_id: str,
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.port.load_timeseries_bundle(artifact_id)

    async def load_feature_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalFeaturePackArtifactData | None:
        return await self.port.load_feature_pack(artifact_id)

    async def load_indicator_series(
        self,
        artifact_id: str | None,
    ) -> TechnicalIndicatorSeriesArtifactData | None:
        return await self.port.load_indicator_series(artifact_id)

    async def save_regime_pack(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_regime_pack(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


@dataclass(frozen=True)
class TechnicalOrchestrator:
    port: ITechnicalArtifactRepository
    summarize_preview: Callable[[JSONObject], JSONObject]
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]
    build_semantic_output_artifact: Callable[[str, JSONObject, str], dict[str, object]]

    async def run_data_fetch(
        self,
        state: Mapping[str, object],
        *,
        market_data_provider: IMarketDataProvider,
    ) -> TechnicalNodeResult:
        return await run_data_fetch_use_case(
            _DataFetchRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            market_data_provider=market_data_provider,
        )

    async def run_feature_compute(
        self,
        state: Mapping[str, object],
        *,
        feature_runtime: FeatureRuntimeService,
        indicator_series_runtime: IndicatorSeriesRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_feature_compute_use_case(
            _FeatureComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            feature_runtime=feature_runtime,
            indicator_series_runtime=indicator_series_runtime,
        )

    async def run_pattern_compute(
        self,
        state: Mapping[str, object],
        *,
        pattern_runtime: PatternRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_pattern_compute_use_case(
            _PatternComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            pattern_runtime=pattern_runtime,
        )

    async def run_alerts_compute(
        self,
        state: Mapping[str, object],
        *,
        alert_runtime: AlertRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_alerts_compute_use_case(
            _AlertsComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            alert_runtime=alert_runtime,
        )

    async def run_fusion_compute(
        self,
        state: Mapping[str, object],
        *,
        fusion_runtime: FusionRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_fusion_compute_use_case(
            _FusionComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            fusion_runtime=fusion_runtime,
        )

    async def run_regime_compute(
        self,
        state: Mapping[str, object],
        *,
        regime_runtime: RegimeRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_regime_compute_use_case(
            _RegimeComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            regime_runtime=regime_runtime,
        )

    async def run_verification_compute(
        self,
        state: Mapping[str, object],
        *,
        verification_runtime: VerificationRuntimeService,
    ) -> TechnicalNodeResult:
        return await run_verification_compute_use_case(
            _VerificationComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            verification_runtime=verification_runtime,
        )

    async def run_semantic_translate(
        self,
        state: Mapping[str, object],
        *,
        assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
        build_full_report_payload_fn: Callable[..., JSONObject],
        interpretation_provider: ITechnicalInterpretationProvider,
    ) -> TechnicalNodeResult:
        return await run_semantic_translate_use_case(
            self,
            state,
            assemble_fn=assemble_fn,
            build_full_report_payload_fn=build_full_report_payload_fn,
            interpretation_provider=interpretation_provider,
        )
