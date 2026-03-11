from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.core_valuation.domain.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.model_selection.domain.entities import (
    FundamentalSelectionReport,
)
from src.agents.fundamental.workflow_orchestrator.application.dto import (
    FundamentalAppContextDTO,
)
from src.agents.fundamental.workflow_orchestrator.application.financial_health_flow import (
    FinancialHealthPayload,
    run_financial_health_flow,
)
from src.agents.fundamental.workflow_orchestrator.application.model_selection_flow import (
    run_model_selection_flow,
)
from src.agents.fundamental.workflow_orchestrator.application.ports import (
    IFundamentalReportRepo,
)
from src.agents.fundamental.workflow_orchestrator.application.services.model_selection_artifact_service import (
    build_and_store_model_selection_artifact,
    enrich_reasoning_with_health_context,
)
from src.agents.fundamental.workflow_orchestrator.application.services.valuation_update_service import (
    build_valuation_error_update,
    build_valuation_missing_inputs_update,
    build_valuation_success_update,
)
from src.agents.fundamental.workflow_orchestrator.application.valuation_flow import (
    run_valuation_flow,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

FundamentalNodeResult = WorkflowNodeResult


@dataclass(frozen=True)
class FundamentalOrchestrator:
    port: IFundamentalReportRepo
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject] | None], JSONObject
    ]
    build_progress_artifact: Callable[[str, JSONObject], AgentOutputArtifactPayload]
    normalize_model_selection_reports: Callable[[list[JSONObject]], list[JSONObject]]
    build_model_selection_report_payload: Callable[
        [
            str,
            str,
            str,
            str,
            str,
            str,
            list[JSONObject],
            list[ForwardSignalPayload] | None,
        ],
        JSONObject,
    ]
    build_model_selection_artifact: Callable[
        [str, str, JSONObject], AgentOutputArtifactPayload
    ]
    build_valuation_artifact: Callable[
        [str | None, str, str, JSONObject], AgentOutputArtifactPayload
    ]

    async def save_financial_reports(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_financial_reports(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_financial_reports(self, artifact_id: str) -> list[JSONObject] | None:
        return await self.port.load_financial_reports(artifact_id)

    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[ForwardSignalPayload] | None] | None:
        return await self.port.load_financial_reports_bundle(artifact_id)

    def enrich_reasoning_with_health_context(
        self,
        reasoning: str,
        financial_reports: list[FundamentalSelectionReport],
    ) -> str:
        return enrich_reasoning_with_health_context(reasoning, financial_reports)

    async def build_and_store_model_selection_artifact(
        self,
        *,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        model_type: str,
        reasoning: str,
        financial_reports: list[JSONObject],
        forward_signals: list[ForwardSignalPayload] | None,
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]:
        return await build_and_store_model_selection_artifact(
            intent_ctx=intent_ctx,
            resolved_ticker=resolved_ticker,
            model_type=model_type,
            reasoning=reasoning,
            financial_reports=financial_reports,
            forward_signals=forward_signals,
            port=self.port,
            summarize_preview=self.summarize_preview,
            normalize_model_selection_reports_fn=self.normalize_model_selection_reports,
            build_model_selection_report_payload_fn=self.build_model_selection_report_payload,
            build_model_selection_artifact_fn=self.build_model_selection_artifact,
        )

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject:
        return build_valuation_missing_inputs_update(
            fundamental=fundamental,
            missing_inputs=missing_inputs,
            assumptions=assumptions,
        )

    def build_valuation_success_update(
        self,
        *,
        fundamental: dict[str, object],
        intent_ctx: dict[str, object],
        ticker: str | None,
        model_type: str,
        reports_raw: list[JSONObject],
        reports_artifact_id: str,
        params_dump: JSONObject,
        calculation_metrics: JSONObject,
        assumptions: list[str],
        build_metadata: JSONObject | None = None,
    ) -> JSONObject:
        return build_valuation_success_update(
            fundamental=fundamental,
            intent_ctx=intent_ctx,
            ticker=ticker,
            model_type=model_type,
            reports_raw=reports_raw,
            reports_artifact_id=reports_artifact_id,
            params_dump=params_dump,
            calculation_metrics=calculation_metrics,
            assumptions=assumptions,
            summarize_preview=self.summarize_preview,
            build_valuation_artifact_fn=self.build_valuation_artifact,
            build_metadata=build_metadata,
        )

    def build_valuation_error_update(self, error: str) -> JSONObject:
        return build_valuation_error_update(error)

    async def run_financial_health(
        self,
        state: Mapping[str, object],
        *,
        fetch_financial_data_fn: Callable[[str], FinancialHealthPayload],
    ) -> FundamentalNodeResult:
        return await run_financial_health_flow(
            self,
            state,
            fetch_financial_data_fn=fetch_financial_data_fn,
        )

    async def run_model_selection(
        self,
        state: Mapping[str, object],
        *,
        select_valuation_model_fn: Callable[
            [CompanyProfile, list[FundamentalSelectionReport]], object
        ],
    ) -> FundamentalNodeResult:
        return await run_model_selection_flow(
            self,
            state,
            select_valuation_model_fn=select_valuation_model_fn,
        )

    async def run_valuation(
        self,
        state: Mapping[str, object],
        *,
        build_params_fn: Callable[
            [str, str | None, list[JSONObject], list[JSONObject] | None],
            ParamBuildResult,
        ],
        get_model_runtime_fn: Callable[[str], object | None],
    ) -> FundamentalNodeResult:
        return await run_valuation_flow(
            self,
            state,
            build_params_fn=build_params_fn,
            get_model_runtime_fn=get_model_runtime_fn,
        )
