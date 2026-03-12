from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from src.agents.news.application.orchestrator import NewsNodeResult, NewsOrchestrator
from src.agents.news.application.ports import (
    FetchContentResult,
    FinbertAnalyzerLike,
    INewsArtifactRepository,
    LLMLike,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.interface.contracts import (
    AIAnalysisModel,
    FinancialNewsItemModel,
    SourceInfoModel,
)
from src.agents.news.interface.preview_projection_service import (
    summarize_news_for_preview,
)
from src.agents.news.interface.prompt_specs import (
    build_analyst_prompt_spec,
    build_selector_prompt_spec,
)
from src.agents.news.interface.serializers import build_news_report_payload
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def _build_news_output_artifact(
    summary: str, preview: JSONObject, report_id: str | None
) -> AgentOutputArtifactPayload:
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


def build_news_orchestrator(*, port: INewsArtifactRepository) -> NewsOrchestrator:
    return NewsOrchestrator(
        port=port,
        summarize_preview=summarize_news_for_preview,
        build_news_report_payload=build_news_report_payload,
        build_output_artifact=_build_news_output_artifact,
    )


@dataclass(frozen=True)
class NewsWorkflowDependencies:
    news_search_multi_timeframe_fn: Callable[
        [str, str | None], Awaitable[list[JSONObject]]
    ]
    get_llm_fn: Callable[[], LLMLike]
    fetch_clean_text_async_fn: Callable[[str], Awaitable[FetchContentResult]]
    generate_news_id_fn: Callable[[str | None, str | None], str]
    get_source_reliability_fn: Callable[[str], float]
    get_finbert_analyzer_fn: Callable[[], FinbertAnalyzerLike]
    item_factory: NewsItemFactoryLike = FinancialNewsItemModel
    source_factory: SourceFactoryLike = SourceInfoModel
    analysis_model_type: type[BaseModel] = AIAnalysisModel


@dataclass(frozen=True)
class NewsWorkflowRunner:
    orchestrator: NewsOrchestrator
    deps: NewsWorkflowDependencies

    async def run_search(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_search(
            state,
            news_search_multi_timeframe_fn=self.deps.news_search_multi_timeframe_fn,
        )

    async def run_selector(self, state: Mapping[str, object]) -> NewsNodeResult:
        selector_prompt = build_selector_prompt_spec()
        return await self.orchestrator.run_selector(
            state,
            get_llm_fn=self.deps.get_llm_fn,
            selector_system_prompt=selector_prompt.system,
            selector_user_prompt=selector_prompt.user,
        )

    async def run_fetch(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_fetch(
            state,
            fetch_clean_text_async_fn=self.deps.fetch_clean_text_async_fn,
            generate_news_id_fn=self.deps.generate_news_id_fn,
            get_source_reliability_fn=self.deps.get_source_reliability_fn,
            item_factory=self.deps.item_factory,
            source_factory=self.deps.source_factory,
        )

    async def run_analyst(self, state: Mapping[str, object]) -> NewsNodeResult:
        analyst_prompt = build_analyst_prompt_spec()
        return await self.orchestrator.run_analyst(
            state,
            get_llm_fn=self.deps.get_llm_fn,
            get_finbert_analyzer_fn=self.deps.get_finbert_analyzer_fn,
            analyst_system_prompt=analyst_prompt.system,
            analyst_user_prompt_basic=analyst_prompt.user_basic,
            analyst_user_prompt_with_finbert=analyst_prompt.user_with_finbert,
            analysis_model_type=self.deps.analysis_model_type,
        )

    async def run_aggregator(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_aggregator(state)


def build_news_workflow_runner(
    *,
    orchestrator: NewsOrchestrator,
    deps: NewsWorkflowDependencies,
) -> NewsWorkflowRunner:
    return NewsWorkflowRunner(orchestrator=orchestrator, deps=deps)
