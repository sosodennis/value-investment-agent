from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.application import use_cases
from src.agents.fundamental.data.ports import (
    FundamentalArtifactPort,
    fundamental_artifact_port,
)
from src.agents.fundamental.interface.mappers import summarize_fundamental_for_preview
from src.common.types import AgentOutputArtifactPayload, JSONObject


@dataclass(frozen=True)
class FundamentalOrchestrator:
    port: FundamentalArtifactPort
    summarize_preview: Callable[[dict[str, object], list[JSONObject]], JSONObject]

    def build_mapper_context(
        self,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        *,
        status: str,
        model_type: str | None = None,
        valuation_summary: str | None = None,
    ) -> dict[str, object]:
        return use_cases.build_mapper_context(
            intent_ctx,
            resolved_ticker,
            status=status,
            model_type=model_type,
            valuation_summary=valuation_summary,
        )

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

    def build_selection_details(
        self, selection: use_cases._ModelSelectionLike
    ) -> dict[str, object]:
        return use_cases.build_selection_details(selection)

    def enrich_reasoning_with_health_context(
        self,
        reasoning: str,
        financial_reports: list[JSONObject],
    ) -> str:
        return use_cases.enrich_reasoning_with_health_context(
            reasoning, financial_reports
        )

    async def build_and_store_model_selection_artifact(
        self,
        *,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        model_type: str,
        reasoning: str,
        financial_reports: list[JSONObject],
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]:
        return await use_cases.build_and_store_model_selection_artifact(
            intent_ctx=intent_ctx,
            resolved_ticker=resolved_ticker,
            model_type=model_type,
            reasoning=reasoning,
            financial_reports=financial_reports,
            port=self.port,
            summarize_preview=self.summarize_preview,
        )

    def resolve_selection_model_type(self, selected_model_value: str) -> str:
        return use_cases.resolve_selection_model_type(selected_model_value)

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject:
        return use_cases.build_valuation_missing_inputs_update(
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
    ) -> JSONObject:
        return use_cases.build_valuation_success_update(
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
        )

    def build_valuation_error_update(self, error: str) -> JSONObject:
        return use_cases.build_valuation_error_update(error)


fundamental_orchestrator = FundamentalOrchestrator(
    port=fundamental_artifact_port,
    summarize_preview=summarize_fundamental_for_preview,
)
