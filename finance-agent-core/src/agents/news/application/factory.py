from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.news.application.orchestrator import NewsNodeResult, NewsOrchestrator
from src.agents.news.data.clients import (
    fetch_clean_text_async,
    generate_news_id,
    get_finbert_analyzer,
    get_source_reliability,
    news_search_multi_timeframe,
)
from src.agents.news.data.ports import news_artifact_port
from src.agents.news.domain.prompt_builder import (
    build_analyst_prompt_spec,
    build_selector_prompt_spec,
)
from src.agents.news.interface.contracts import (
    AIAnalysisModel,
    FinancialNewsItemModel,
    SourceInfoModel,
)
from src.agents.news.interface.mappers import summarize_news_for_preview
from src.agents.news.interface.serializers import build_news_report_payload
from src.infrastructure.llm.provider import get_llm
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
)


def _build_news_output_artifact(
    summary: str, preview: dict[str, object], report_id: str | None
) -> dict[str, object] | None:
    reference = None
    if report_id:
        reference = ArtifactReference(
            artifact_id=report_id,
            download_url=f"/api/artifacts/{report_id}",
            type=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
        summary=summary,
        preview=preview,
        reference=reference,
    )


def build_news_orchestrator() -> NewsOrchestrator:
    return NewsOrchestrator(
        port=news_artifact_port,
        summarize_preview=summarize_news_for_preview,
        build_news_report_payload=build_news_report_payload,
        build_output_artifact=_build_news_output_artifact,
    )


@dataclass(frozen=True)
class NewsWorkflowRunner:
    orchestrator: NewsOrchestrator

    async def run_search(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_search(
            state,
            news_search_multi_timeframe_fn=news_search_multi_timeframe,
        )

    async def run_selector(self, state: Mapping[str, object]) -> NewsNodeResult:
        selector_prompt = build_selector_prompt_spec()
        return await self.orchestrator.run_selector(
            state,
            get_llm_fn=get_llm,
            selector_system_prompt=selector_prompt.system,
            selector_user_prompt=selector_prompt.user,
        )

    async def run_fetch(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_fetch(
            state,
            fetch_clean_text_async_fn=fetch_clean_text_async,
            generate_news_id_fn=generate_news_id,
            get_source_reliability_fn=get_source_reliability,
            item_factory=FinancialNewsItemModel,
            source_factory=SourceInfoModel,
        )

    async def run_analyst(self, state: Mapping[str, object]) -> NewsNodeResult:
        analyst_prompt = build_analyst_prompt_spec()
        return await self.orchestrator.run_analyst(
            state,
            get_llm_fn=get_llm,
            get_finbert_analyzer_fn=get_finbert_analyzer,
            analyst_system_prompt=analyst_prompt.system,
            analyst_user_prompt_basic=analyst_prompt.user_basic,
            analyst_user_prompt_with_finbert=analyst_prompt.user_with_finbert,
            analysis_model_type=AIAnalysisModel,
        )

    async def run_aggregator(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_aggregator(state)


def build_news_workflow_runner() -> NewsWorkflowRunner:
    return NewsWorkflowRunner(orchestrator=build_news_orchestrator())


news_workflow_runner = build_news_workflow_runner()
