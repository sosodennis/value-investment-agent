from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.technical.application.ports import (
    ITechnicalArtifactRepository,
    ITechnicalBacktestRuntime,
    ITechnicalFracdiffRuntime,
    ITechnicalInterpretationProvider,
    ITechnicalMarketDataProvider,
)
from src.agents.technical.application.use_cases import (
    run_data_fetch_use_case,
    run_fracdiff_compute_use_case,
    run_semantic_translate_use_case,
)
from src.agents.technical.domain.signal_policy import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.interface.artifacts.artifact_data_models import PriceSeriesArtifactData
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


@dataclass(frozen=True)
class _FracdiffComputeRuntimeAdapter:
    port: ITechnicalArtifactRepository
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]

    async def load_price_series(
        self,
        artifact_id: str,
    ) -> PriceSeriesArtifactData | None:
        return await self.port.load_price_series(artifact_id)

    async def save_chart_data(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_chart_data(
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
        market_data_provider: ITechnicalMarketDataProvider,
    ) -> TechnicalNodeResult:
        return await run_data_fetch_use_case(
            _DataFetchRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            market_data_provider=market_data_provider,
        )

    async def run_fracdiff_compute(
        self,
        state: Mapping[str, object],
        *,
        fracdiff_runtime: ITechnicalFracdiffRuntime,
    ) -> TechnicalNodeResult:
        return await run_fracdiff_compute_use_case(
            _FracdiffComputeRuntimeAdapter(
                port=self.port,
                build_progress_artifact=self.build_progress_artifact,
            ),
            state,
            fracdiff_runtime=fracdiff_runtime,
        )

    async def run_semantic_translate(
        self,
        state: Mapping[str, object],
        *,
        assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
        build_full_report_payload_fn: Callable[..., JSONObject],
        fracdiff_runtime: ITechnicalFracdiffRuntime,
        market_data_provider: ITechnicalMarketDataProvider,
        interpretation_provider: ITechnicalInterpretationProvider,
        backtest_runtime: ITechnicalBacktestRuntime,
    ) -> TechnicalNodeResult:
        return await run_semantic_translate_use_case(
            self,
            state,
            assemble_fn=assemble_fn,
            build_full_report_payload_fn=build_full_report_payload_fn,
            fracdiff_runtime=fracdiff_runtime,
            market_data_provider=market_data_provider,
            interpretation_provider=interpretation_provider,
            backtest_runtime=backtest_runtime,
        )
