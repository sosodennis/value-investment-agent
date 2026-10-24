from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from src.agents.news.application.orchestrator import NewsNodeResult, NewsOrchestrator
from src.agents.news.application.ports import (
    FetchContentResult,
    INewsArtifactRepository,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.interface.contracts import (
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
from src.llm_provider.entrypoint import LLMProviderPort, ModelRoute
from src.model_inference.entrypoint import ModelInference
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
            download_url=f"/api/v1/artifacts/{report_id}",
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
    llm_provider: LLMProviderPort
    llm_route: ModelRoute
    fetch_clean_text_async_fn: Callable[[str], Awaitable[FetchContentResult]]
    generate_news_id_fn: Callable[[str | None, str | None], str]
    get_source_reliability_fn: Callable[[str], float]
    model_inference: ModelInference
    item_factory: NewsItemFactoryLike = FinancialNewsItemModel
    source_factory: SourceFactoryLike = SourceInfoModel


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
            llm_provider=self.deps.llm_provider,
            llm_route=self.deps.llm_route,
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
            llm_provider=self.deps.llm_provider,
            llm_route=self.deps.llm_route,
            model_inference=self.deps.model_inference,
            analyst_system_prompt=analyst_prompt.system,
            analyst_user_prompt_basic=analyst_prompt.user_basic,
            analyst_user_prompt_with_finbert=analyst_prompt.user_with_finbert,
        )

    async def run_aggregator(self, state: Mapping[str, object]) -> NewsNodeResult:
        return await self.orchestrator.run_aggregator(state)


def build_news_workflow_runner(
    *,
    orchestrator: NewsOrchestrator,
    deps: NewsWorkflowDependencies,
) -> NewsWorkflowRunner:
    return NewsWorkflowRunner(orchestrator=orchestrator, deps=deps)
